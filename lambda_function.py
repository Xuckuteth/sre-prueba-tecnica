import json
import os
import socket
import hashlib
import traceback
from datetime import datetime
import boto3

def redis_cmd(host, port, *args):
    """Ejecuta un comando de Redis sobre TCP mediante sockets nativos."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2.0)
    s.connect((host, port))
    cmd = f"*{len(args)}\r\n"
    for arg in args:
        cmd += f"${len(str(arg))}\r\n{arg}\r\n"
    s.sendall(cmd.encode('utf-8'))
    response = s.recv(4096).decode('utf-8', errors='ignore')
    s.close()
    return response

def lambda_handler(event, context):
    print(f"Evento recibido en Lambda: {json.dumps(event)}")
    redis_host = os.environ.get('REDIS_HOST', 'host.docker.internal')
    redis_port = int(os.environ.get('REDIS_PORT', '6379'))
    bucket_name = os.environ.get('BUCKET_NAME', 'sre-local-bucket-ei908k')

    try:
        # 1. Extraer body del POST o query string
        body_raw = event.get('body') or ""
        if event.get('isBase64Encoded', False):
            import base64
            body_raw = base64.b64decode(body_raw).decode('utf-8')

        try:
            payload_json = json.loads(body_raw) if body_raw else {}
        except Exception:
            payload_json = {"raw_content": body_raw}

        # Generar ID de caché basado en el campo 'id' o en el Hash MD5 del body
        item_id = str(payload_json.get('id') or hashlib.md5(body_raw.encode('utf-8') or b'default').hexdigest()[:10])
        cache_key = f"item:{item_id}"

        # 2. Consultar Redis (CACHE HIT)
        try:
            resp = redis_cmd(redis_host, redis_port, "GET", cache_key)
            if resp and not resp.startswith("$-1"):
                lines = resp.split("\r\n")
                cached_val = lines[1] if len(lines) > 1 else resp
                return {
                    "statusCode": 200,
                    "headers": {
                        "Content-Type": "application/json",
                        "Access-Control-Allow-Origin": "*",
                        "X-Cache": "HIT"
                    },
                    "body": cached_val
                }
        except Exception as cache_err:
            print(f"Advertencia al consultar Redis (GET): {cache_err}")

        # 3. CACHE MISS: Procesar payload y guardar con TTL = 60s
        now = datetime.utcnow()
        result_data = {
            "id": item_id,
            "status": "processed",
            "processed_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "input_payload": payload_json,
            "hash_signature": hashlib.sha256(body_raw.encode('utf-8')).hexdigest() if body_raw else None,
            "message": "Procesado correctamente por Lambda en LocalStack"
        }
        json_output = json.dumps(result_data)

        # Guardar en Redis con TTL = 60s
        try:
            redis_cmd(redis_host, redis_port, "SETEX", cache_key, "60", json_output)
        except Exception as cache_write_err:
            print(f"Advertencia al escribir en Redis (SETEX): {cache_write_err}")

        # 4. Guardar archivo en S3 (results/<fecha>/<id>.json)
        try:
            localstack_host = os.environ.get('LOCALSTACK_HOSTNAME', 'host.docker.internal')
            endpoint_url = f"http://{localstack_host}:4566"
            s3_client = boto3.client(
                's3',
                endpoint_url=endpoint_url,
                aws_access_key_id='mock_access_key',
                aws_secret_access_key='mock_secret_key',
                region_name='us-east-1'
            )
            today = now.strftime('%Y-%m-%d')
            s3_key = f"results/{today}/{item_id}.json"

            s3_client.put_object(
                Bucket=bucket_name,
                Key=s3_key,
                Body=json_output,
                ContentType='application/json'
            )
        except Exception as s3_err:
            print(f"Advertencia al guardar en S3: {s3_err}")

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "X-Cache": "MISS"
            },
            "body": json_output
        }

    except Exception as unhandled_err:
        error_trace = traceback.format_exc()
        print(f"ERROR 500 no controlado: {error_trace}")
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps({
                "error": "InternalServerError",
                "message": str(unhandled_err),
                "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            })
        }