from typing import Optional
from multiprocessing import Process, Queue
from fastapi import FastAPI, Request
import boto3
from botocore.exceptions import ClientError
import argparse
import asyncio
import base64
import os
import json
import datetime
import time
import helper
import interpreter

app = FastAPI()
alert_queue = Queue(3)

def process_alert_queue(args, q):
  sns = boto3.client("sns", aws_access_key_id=args.access_key_id, aws_secret_access_key=args.secret_access_key)
  s3 = boto3.client("s3", aws_access_key_id=args.access_key_id, aws_secret_access_key=args.secret_access_key)
  while True:
    # continuously read from alert queue and dispatch stream source to interpreter
    source = q.get()
    print('Starting new job analyzing source: {}'.format(source))
    interpret, inference_size, labels = helper.load_interpreter(os.path.join(args.model_dir, args.model), os.path.join(args.model_dir, args.labels))
    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(asyncio.gather(interpreter.process_webstream(args, interpret, source, labels)))
    if 'INTRUDER' in result['message']:
      print('{} - Notifying SNS with file {}'.format(result['message'], result['file']))
      try:
        response = s3.upload_file(result['file'], args.s3_bucket_name, os.path.basename(result['file']))
        print('S3 response: {}'.format(response))
        response = sns.publish(
          TopicArn=args.sns_topic_arn,
          Message='{} - check {} in S3'.format(result['message'], os.path.basename(result['file'])),
          Subject="Alert",
        )
        print('SNS response: {}'.format(response))
      except ClientError as e:
        print(e)
    else:
      print('FALSE ALARM!')
@app.get("/")
def read_root():
  return {"Hello": "World"}

@app.post("/disarm")
async def handle_disarm(request: Request):
  data = await request.json()
  interpreter_task.join()
  return data

@app.post("/arm")
async def handle_arm(request: Request):
  data = await request.json()
  interpreter_task.join()
  interpreter_task.start()
  return data

@app.post("/alert")
async def handle_alert(request: Request):
  data = await request.json()

  if data['source'] is not None:
    print('Processing stream from {}'.format(data['source']))
    alert_queue.put(data['source'])
  return data

if __name__ == "__main__":
  parser = argparse.ArgumentParser()
  parser.add_argument('--region', '-r', type=str, default='us-east-1')
  parser.add_argument('--access_key_id', '-k', type=str, required=True)
  parser.add_argument('--secret_access_key', '-s', type=str, required=True)
  parser.add_argument('--sns_topic_arn', '-t', type=str, required=True)
  parser.add_argument('--s3_bucket_name', '-b', type=str, default='panoptix')
  parser.add_argument('--timeout_seconds', type=int, default=30)
  parser.add_argument('--top_k', type=int, default=5)
  parser.add_argument('--threshold', type=float, default=0.5)
  parser.add_argument('--model_dir', '-d', type=str, default='models')
  parser.add_argument('--output_dir', '-o', type=str, default='output')
  parser.add_argument('--model', '-m', type=str, default='ssd_mobilenet_v2_face_quant_postprocess_edgetpu.tflite')
  args = parser.parse_args()

  interpreter_task = Process(target=process_alert_queue, args=(args, alert_queue))
  interpreter_task.start()
