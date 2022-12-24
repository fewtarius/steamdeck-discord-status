import asyncio
import json
import logging
import os
import socket
import struct
import time
import uuid

CLIENT_ID = '1055680235682672682'

logging.basicConfig(filename="/tmp/discord-status.log",
                    format='[Template] %(asctime)s %(levelname)s %(message)s',
                    filemode='w+',
                    force=True)
logger=logging.getLogger()
logger.setLevel(logging.INFO) # can be changed to logging.DEBUG for debugging issues

OP_HANDSHAKE = 0
OP_FRAME = 1
OP_CLOSE = 2
OP_PING = 3
OP_PONG = 4

connected = False
client = None
runningAppId = '0'

class Plugin:
    async def rand(self, app):
        logger.info("rand")
        logger.info("Called with %s ", app)

    async def clear_activity(self, appId):
        global connected
        global runningAppId

        if (appId == '0'):
            return False
        
        logger.info('Called clear activity')

        if not connected:
            await self.connect(self)

        data = {
            'cmd': 'SET_ACTIVITY',
            'args': {
                'pid': os.getpid()
            },
            'nonce': str(uuid.uuid4())
        }

        op, result = Plugin.send_recv(data)
        logger.info("result %s", result)

        runningAppId = '0'

        return True

    # A normal method. It can be called from JavaScript using call_plugin_function("method_1", argument1, argument2)
    async def update_activity(self, actionType, appId, action, details):
        global connected
        global runningAppId

        logger.info('Called update activity: %s %s %s %s', actionType, appId, action, details)
        if not connected:
            await self.connect(self)

        data = {
            'cmd': 'SET_ACTIVITY',
            'args': {
                'pid': os.getpid(),
                'activity': {
                    'state': 'on Steam Deck',
                    'details': 'Playing {}'.format(details['display_name']),
                    'assets': {
                        'large_image': 'https://cdn.akamai.steamstatic.com/steam/apps/{}/hero_capsule.jpg'.format(appId),
                        'small_image': 'steamdeck-logo'
                    },
                    'timestamps': {
                        'start': round(time.time())
                    }
                }
            },
            'nonce': str(uuid.uuid4())
        }

        op, result = Plugin.send_recv(data)
        logger.info("result %s", result)

        runningAppId = appId
        return True

    async def reconnect(self):
        global connected

        if connected:
            Plugin.send({}, op=OP_PING)

            if connected:
                logger.debug("Already connected")
                return True

        logger.info("Attempting to reconnect")
        await self.connect(self)

        return connected

    # Asyncio-compatible long-running code, executed in a task when the plugin is loaded
    async def _main(self):
        global connected
        global client

        logger.info("Starting Steam Deck Discord Status plugin")
        connected = False

        await self.connect(self)
    
    # Function called first during the unload process, utilize this to handle your plugin being removed
    async def _unload(self):
        if connected:
            logger.info("Closing connection")
            self.close(self)
        else:
            logger.info("Wasn't connected")

    async def connect(self):
        global client
        global connected

        tries = 0
        while not connected and tries < 5:
            client = socket.socket(socket.AF_UNIX)
            client.settimeout(5)
            logger.debug('Attempting to connect to socket...')
            tries = tries + 1
            try:
                client.connect('/run/user/1000/app/com.discordapp.Discord/discord-ipc-0')
            except ConnectionResetError:
                if (client):
                    client.close()
                client = None
                connected = False
                await asyncio.sleep(5)
            except OSError as e:
                logger.error("Socket not available: {}".format(e))
                await asyncio.sleep(5)
            except BaseException as e:
                logger.error("Some other error occurred: {}".format(e))
            else:
                logger.info('Connected to IPC socket')
                await self._handshake(self)

    def close(self):
        global connected
        global client

        try:
            self.send({}, op=OP_CLOSE)
        finally:
            try:
                if (client):
                    client.close()
            except BrokenPipeError as e:
                client = None
                logger.warn("Pipe is broken, client closed unexpectedly")
            connected = False
            logger.info("Closed")

    async def _handshake(self):
        global connected

        if client is None:
            return self.connect(self)

        ret_op, ret_data = Plugin.send_recv({'v': 1, 'client_id': CLIENT_ID}, op=OP_HANDSHAKE)
        if ret_op == OP_FRAME and ret_data['cmd'] == 'DISPATCH' and ret_data['evt'] == 'READY':
            connected = True
            logger.info('All set')

            return
        else:
            logger.error("Handshake failed %s", ret_data)


    def _recv_exactly(size) -> bytes:
        buf = b""
        size_remaining = size
        while size_remaining:
            chunk = Plugin._recv(size_remaining)
            buf += chunk
            size_remaining -= len(chunk)
        return buf

    def _recv_header():
        header = Plugin._recv_exactly(8)
        return struct.unpack("<II", header)

    def send_recv(data, op=OP_FRAME):
        Plugin.send(data, op)
        return Plugin.recv()

    def send(data, op=OP_FRAME):
        logger.debug("sending %s", data)
        data_str = json.dumps(data, separators=(',', ':'))
        data_bytes = data_str.encode('utf-8')
        header = struct.pack("<II", op, len(data_bytes))
        Plugin._write(header)
        Plugin._write(data_bytes)

    def recv():
        op, length = Plugin._recv_header()
        payload = Plugin._recv_exactly(length)
        data = json.loads(payload.decode('utf-8'))
        logger.debug("received %s", data)
        return op, data

    def _write(data: bytes):
        global client
        global connected

        try:
            if client:
                client.sendall(data)
            else:
                connected = False
        except BrokenPipeError as e:
            logger.warn("Pipe is broken")
            client = None
            connected = False
            
    def _recv(size: int) -> bytes:
        global client
        global connected

        try:
            if client:
                return client.recv(size)
            else:
                connected = False
        except BrokenPipeError as e:
            logger.warn("Pipe is broken")
            client = None
            connected = False