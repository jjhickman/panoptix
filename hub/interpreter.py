import datetime
import base64
import os
import socketio
import asyncio
from PIL import Image
from async_timeout import timeout
from pycoral.adapters import common
from pycoral.adapters import detect
from io import BytesIO
interpreter = None
sio= None

async def process_webstream(args, interpret, inference_size, source, labels):
    global result, sio, interpreter
    interpreter = interpret
    result = {}
    sio = socketio.AsyncClient()
    try:
        async with timeout(args.timeout_seconds):
            @sio.event
            async def connect():
                global logger
                print('Connected at {}! Processing stream...'.format(datetime.datetime.now()))

            @sio.on('image')
            async def on_image(message):
                global result, sio, interpreter
                try:
                    decoded = base64.b64decode(message)
                    image = Image.open(BytesIO(decoded))
                    _, scale = common.set_resized_input(interpreter, image.size, lambda size: image.resize(size, Image.ANTIALIAS))
                    interpreter.invoke()
                    objects = detect.get_objects(interpreter, args.threshold, scale)[:args.top_k]
                    if len(objects) > 0:
                        print('Person detected!')
                        filepath = os.path.join(args.output_dir, '{}.jpg'.format(datetime.datetime.now()))
                        result = {
                            'message': 'INTRUDER FOUND',
                            'file': filepath
                        }
                        image.save(filepath)
                        await sio.disconnect()
                except Exception as e:
                    print('Error parsing message from socketio server: {}'.format(e))
                    result = {
                        'message': 'INTERPRETER_ERROR: {}'.format(e)
                    }
                    await sio.disconnect()
            await sio.connect(source)
            await sio.wait()
    except asyncio.TimeoutError as e:
        await sio.disconnect()
        print('Disconnecting. Job expired')
        result = {
            'message': 'OKAY'
        }
    except Exception as e:
        print('Exception processing stream: {}'.format(e))
        result = {
            'message': 'EXCEPTION: {}'.format(e)
        }
    return result