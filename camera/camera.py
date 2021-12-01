import time
import argparse
import socket
import asyncio
from aiohttp.payload_streamer import StreamWrapperPayload
import socketio
import cv2
import base64
import logging
import multiprocessing
from detector import Detector
import requests
import aiohttp
from aiohttp import web

stream_url = ''
sio = socketio.AsyncServer()
logger = None
static_back = None
detector = []
frame_queue = multiprocessing.Queue(1)

"""
=============================================================================
    REST API routes
=============================================================================
"""
# GET request handler for stream
async def index(request):
    global logger
    index_html = """<html>
    <head><title>""" + socket.gethostname() + """</title></head>
        <body>
        <h1>""" + socket.gethostname() + """</h1>
        <img id='image' src=''/>
        <script src="https://cdn.socket.io/3.1.1/socket.io.min.js" integrity="sha384-gDaozqUvc4HTgo8iZjwth73C6dDDeOJsAgpxBcMpZYztUfjHXpzrpdrHRdVp8ySO" crossorigin="anonymous"></script>
        <script>
            const socket = io.connect('""" + stream_url + """');
            console.log("Connection started")
            socket.on('image', (image) => {
                console.log("New image!");
                let imageStr = new TextDecoder("utf-8").decode(image);
                document.getElementById('image').src = 'data:image/jpeg;base64,' + imageStr;
            });
        </script>
    </body>
    </html>"""
    logger.debug('Request for stream: {}\n\nSending: {}'.format(request, index_html))
    return web.Response(text=index_html, content_type='text/html')

def detect(config, q, url, logger):
    detector = Detector(bg_history=10,
      bg_skip_frames=1,
      movement_frames_history=2,
      brightness_discard_level=5,
      bg_subs_scale_percent=0.2,
      pixel_compression_ratio=0.1,
      group_boxes=True,
      expansion_step=5)
    awake_time = time.time()
    while True:
        frame = q.get()
        if frame is None:
            continue
        boxes, f = detector.detect(frame)
        if len(boxes) > 0 and time.time() >= awake_time:
            response = requests.post(url, data={'source': stream_url, 'time': round(time.time() * 1000)}, timeout=500)
            if response.status_code == 200:
                logger.debug('Successfully notified hub!')
            else:
                logger.debug(response.text)

"""
=============================================================================
    SocketIO camera capture async loop for web stream and for GPIO input
=============================================================================
"""
async def stream(app, q):
    global logger, stream_url, frame_queue
    refresh_seconds = 1.0 / 20
    logger.debug('Updating stream every {} seconds'.format(refresh_seconds))
    try:
        while True:
            ret, frame = app['capture'].read()
            frame_queue.put(frame)
            if ret == False:
                logger.error("FAILED READING FROM CAPTURE")
                break
            ret, jpg_image = cv2.imencode('.jpg', frame)
            base64_image = base64.b64encode(jpg_image)
            await app['socket'].emit('image', base64_image)
            await asyncio.sleep(refresh_seconds)
        logger.debug('Ended stream!')
    except asyncio.CancelledError:
        logger.debug('Stream cancelled')

"""
=============================================================================
    SocketIO handles
=============================================================================
"""
@sio.on('finished')
async def handle_finish(sid, data):
    logger.info('Client {} finished job. Disconnecting...'.format(sid))
    await sio.disconnect(sid)

@sio.event
async def connect(sid, environ):
    logger.info('CONNECTED to client with id: {}'.format(sid))

@sio.event
def disconnect(sid):
    logger.info('DISCONNECTED from client with id: {}'.format(sid))


"""
=============================================================================
   Setup and configuration for GPIO, socketio, and web server/API
=============================================================================
"""
def initialize():
    global sio, stream_url, logger

    parser = argparse.ArgumentParser()
    parser.add_argument('--endpoint', '-e', type=str, default='192.168.50.200')
    parser.add_argument('--username', '-u', type=str, default='username')
    parser.add_argument('--password', '-p', type=str, default='password')
    parser.add_argument('--cooldown', '-c', type=int, default=15)
    parser.add_argument('--threshold', '-t', type=float, default=0.1)
    args = parser.parse_args()

    log_formatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")
    logger = logging.getLogger('aiohttp.server')
    logger.setLevel(logging.DEBUG)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    logger.addHandler(console_handler)

    app = web.Application()
    app['config'] = args
    print(socket.gethostbyname(socket.gethostname()))
    stream_url = 'http://{}:{}'.format(socket.gethostbyname(socket.gethostname()), 8888)
    print('Streaming from {}'.format(stream_url))
    sio.attach(app)
    app['socket'] = sio


    app.router.add_get('/', index)
    app.on_startup.append(start_tasks)
    app.on_cleanup.append(cleanup_tasks)
    return app, socket.gethostbyname(socket.gethostname())
    #return app, app['config'].address


async def start_tasks(app):
    app['capture'] = cv2.VideoCapture(0)
    app['stream'] = app.loop.create_task(stream(app, frame_queue))

async def cleanup_tasks(app):
    app['capture'].release()
    cv2.destroyAllWindows()

if __name__ == '__main__':

    app, address = initialize()
    worker = multiprocessing.Process(target=detect, args=(app['config'], frame_queue, stream_url, logger))
    worker.start()

    web.run_app(app, host=socket.gethostbyname(socket.gethostname()), port=8888)