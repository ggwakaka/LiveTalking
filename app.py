###############################################################################
#  Copyright (C) 2024 LiveTalking@lipku https://github.com/lipku/LiveTalking
#  email: lipku@foxmail.com
# 
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#  
#       http://www.apache.org/licenses/LICENSE-2.0
# 
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
###############################################################################
import os
import sys

# server.py
from flask import Flask, render_template,send_from_directory,request, jsonify
from flask_sockets import Sockets
import base64
import json
import requests
#import gevent
#from gevent import pywsgi
#from geventwebsocket.handler import WebSocketHandler
import re
import numpy as np
from threading import Thread,Event
#import multiprocessing
import torch.multiprocessing as mp

from aiohttp import web
import aiohttp
import aiohttp_cors
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.rtcrtpsender import RTCRtpSender
from webrtc import HumanPlayer
from basereal import BaseReal
from llm import llm_response

import argparse
import random
import shutil
import asyncio
import torch
from typing import Dict
from logger import logger


app = Flask(__name__)
#sockets = Sockets(app)
nerfreals:Dict[int, BaseReal] = {} #sessionid:BaseReal
opt = None
model = None

#####webrtc###############################
pcs = set()

def randN(N)->int:
    '''生成长度为 N的随机数 '''
    min = pow(10, N - 1)
    max = pow(10, N)
    return random.randint(min, max - 1)

def build_nerfreal(sessionid)->BaseReal:
    opt.sessionid=sessionid
    opt.model_id=get_model_id(sessionid)
    from lipreal import load_avatar
    avatar = load_avatar(f"wav2lip256_avatar{opt.model_id}")
    if opt.model == 'wav2lip':
        from lipreal import LipReal
        nerfreal = LipReal(opt,model,avatar)
    elif opt.model == 'musetalk':
        from musereal import MuseReal
        nerfreal = MuseReal(opt,model,avatar)
    elif opt.model == 'ernerf':
        from nerfreal import NeRFReal
        nerfreal = NeRFReal(opt,model,avatar)
    elif opt.model == 'ultralight':
        from lightreal import LightReal
        nerfreal = LightReal(opt,model,avatar)
    return nerfreal

#@app.route('/offer', methods=['POST'])
# async def offer(request):
#     params = await request.json()
#     offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
#
#     if len(nerfreals) >= opt.max_session:
#         logger.info('reach max session')
#         return -1
#     sessionid = str(randN(6)) #len(nerfreals)
#     logger.info('sessionid=%d',sessionid)
#     nerfreals[sessionid] = None
#     nerfreal = await asyncio.get_event_loop().run_in_executor(None, build_nerfreal,sessionid)
#     nerfreals[sessionid] = nerfreal
#
#     pc = RTCPeerConnection()
#     pcs.add(pc)
#
#     @pc.on("connectionstatechange")
#     async def on_connectionstatechange():
#         logger.info("Connection state is %s" % pc.connectionState)
#         if pc.connectionState == "failed":
#             await pc.close()
#             pcs.discard(pc)
#             if sessionid in nerfreals:
#                 del nerfreals[sessionid]
#         if pc.connectionState == "closed":
#             pcs.discard(pc)
#             del nerfreals[sessionid]
#
#     player = HumanPlayer(nerfreals[sessionid])
#     audio_sender = pc.addTrack(player.audio)
#     video_sender = pc.addTrack(player.video)
#     capabilities = RTCRtpSender.getCapabilities("video")
#     preferences = list(filter(lambda x: x.name == "H264", capabilities.codecs))
#     preferences += list(filter(lambda x: x.name == "VP8", capabilities.codecs))
#     preferences += list(filter(lambda x: x.name == "rtx", capabilities.codecs))
#     transceiver = pc.getTransceivers()[1]
#     transceiver.setCodecPreferences(preferences)
#
#     await pc.setRemoteDescription(offer)
#
#     answer = await pc.createAnswer()
#     await pc.setLocalDescription(answer)
#
#     #return jsonify({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type})
#
#     return web.Response(
#         content_type="application/json",
#         text=json.dumps(
#             {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type, "sessionid":sessionid}
#         ),
#     )

async def human(request):
    params = await request.json()

    sessionid = params.get('sessionid','')
    logger.info(f'sessionid={sessionid}')

    if sessionid not in nerfreals:
        return web.Response(
            status=400,
            content_type="application/json",
            text=json.dumps(
                {"code": -1, "data":"sessionid not exist"}
            ),
        )

    if params.get('interrupt'):
        nerfreals[sessionid].flush_talk()

    if params['type']=='echo':
        nerfreals[sessionid].put_msg_txt(params['text'], eventpoint={
            "messageid": params.get('messageid', None),
            "queueid": params.get('queueid', None),
        })
    elif params['type']=='chat':
        res=await asyncio.get_event_loop().run_in_executor(None, llm_response, params['text'],nerfreals[sessionid])                         
        #nerfreals[sessionid].put_msg_txt(res)

    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"code": 0, "data":"ok"}
        ),
    )

async def humanaudio(request):
    try:
        form= await request.post()
        sessionid = form.get('sessionid','')
        fileobj = form["file"]
        filename=fileobj.filename
        filebytes=fileobj.file.read()
        nerfreals[sessionid].put_audio_file(filebytes)

        return web.Response(
            content_type="application/json",
            text=json.dumps(
                {"code": 0, "msg":"ok"}
            ),
        )
    except Exception as e:
        return web.Response(
            content_type="application/json",
            text=json.dumps(
                {"code": -1, "msg":"err","data": ""+e.args[0]+""}
            ),
        )

async def set_audiotype(request):
    params = await request.json()

    sessionid = params.get('sessionid','')
    nerfreals[sessionid].set_curr_state(params['audiotype'],params['reinit'])

    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"code": 0, "data":"ok"}
        ),
    )

async def record(request):
    params = await request.json()

    sessionid = params.get('sessionid','')
    if params['type']=='start_record':
        # nerfreals[sessionid].put_msg_txt(params['text'])
        nerfreals[sessionid].start_recording()
    elif params['type']=='end_record':
        nerfreals[sessionid].stop_recording()
    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"code": 0, "data":"ok"}
        ),
    )


async def upload(request):
    form = await request.post()
    model_id = int(form.get('sessionid', 0))
    logger.info(f'model_id={model_id}')

    fileobj = form["file"]
    filebytes = fileobj.file.read()
    filename = fileobj.filename
    file_temp_path = f"/tmp/{filename}"
    # 存为临时文件
    with open(file_temp_path, "wb") as f:
        f.write(filebytes)
    from wav2lip.genavatar import main
    logger.info("start video split")

    from asgiref.sync import sync_to_async
    await sync_to_async(main)(f"wav2lip256_avatar{model_id}", file_temp_path, 256, replace=True)
    logger.info("end vudei split")

    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"code": 0, "msg": "ok"}
        ),
    )


async def upload_sound(request):
    form = await request.post()
    model_id = int(form.get('sessionid', 0))
    text = form.get('text', "未知")
    logger.info(f'model_id={model_id}')

    fileobj = form["file"]
    filebytes = fileobj.file.read()
    file_temp_path = f"./data/sounds/{model_id}.wav"
    with open(file_temp_path, "wb") as f:
        f.write(filebytes)

    file_temp_path = f"./data/sounds/{model_id}.txt"
    with open(file_temp_path, "wb") as f:
        f.write(text.encode('utf-8'))

    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"code": 0, "msg": "ok"}
        ),
    )


async def is_speaking(request):
    params = await request.json()

    sessionid = params.get('sessionid','')
    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"code": 0, "data": nerfreals[sessionid].is_speaking()}
        ),
    )


async def start(request):
    form = await request.json()
    sessionid = form.get('sessionid', '')
    logger.info(f'sessionid={sessionid} start')
    if sessionid == '':
        return web.Response(
            status=400,
            content_type="application/json",
            text=json.dumps(
                {"code": -1, "msg": "model is not found"}
            ),
        )

    if sessionid in nerfreals:
        logger.info(f'{sessionid} pc.close()')
        await nerfreals[sessionid].pc.close()
    push_url = opt.push_url + sessionid
    await run(push_url, sessionid)

    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"code": 0, "msg": "ok"}
        ),
    )


async def stop(request):
    form = await request.json()
    sessionid = form.get('sessionid', '')
    logger.info(f'sessionid={sessionid} stop')
    if sessionid == '':
        return web.Response(
            status=400,
            content_type="application/json",
            text=json.dumps(
                {"code": -1, "msg": "model is not found"}
            ),
        )

    if sessionid in nerfreals:
        logger.info(f'sessionid={sessionid} pc.close')
        await nerfreals[sessionid].pc.close()
        del nerfreals[sessionid]

    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"code": 0, "msg": "ok"}
        ),
    )

async def is_start(request):
    form = await request.json()
    sessionid = form.get('sessionid', '')
    logger.info(f'sessionid={sessionid}')
    if sessionid == '':
        return web.Response(
            status=400,
            content_type="application/json",
            text=json.dumps(
                {"code": -1, "msg": "model is not found"}
            ),
        )

    result = False
    if sessionid in nerfreals:
        response = requests.get("http://127.0.0.1:1985/api/v1/streams")
        if response.ok:
            res = response.json()
            if res.get("code", -1) == 0:
                for stream in res.get("streams", []):
                    if stream["name"].endswith(f"{sessionid}"):
                        result = True

    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"code": 0, "data": result}
        ),
    )

def get_model_id(sessionid):
    return sessionid.split("-")[0]


async def check_model(request):
    form = await request.json()
    sessionid = form.get('sessionid', '')
    logger.info(f'sessionid={sessionid} check_model')
    if sessionid == '':
        return web.Response(
            status=400,
            content_type="application/json",
            text=json.dumps(
                {"code": -1, "msg": "model is not found"}
            ),
        )
    model_id = get_model_id(sessionid)
    result = False
    if os.path.exists(f"./data/avatars/wav2lip256_avatar{model_id}") \
            and os.path.exists(f"./data/sounds/{model_id}.txt"):
        result = True
    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"code": 0, "data": result}
        ),
    )


async def on_shutdown(app):
    # close peer connections
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()

async def post(url,data):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url,data=data) as response:
                return await response.text()
    except aiohttp.ClientError as e:
        logger.info(f'Error: {e}')

async def run(push_url,sessionid):
    logger.info(f'push_url={push_url}, sessionid={sessionid}')
    nerfreal = await asyncio.get_event_loop().run_in_executor(None, build_nerfreal,sessionid)
    nerfreals[sessionid] = nerfreal

    pc = RTCPeerConnection()
    pcs.add(pc)
    nerfreal.pc=pc
    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        logger.info("Connection state is %s" % pc.connectionState)
        if pc.connectionState == "failed" or pc.connectionState == "closed":
            await pc.close()
            pcs.discard(pc)
            if sessionid in nerfreals:
                del nerfreals[sessionid]

    player = HumanPlayer(nerfreals[sessionid])
    audio_sender = pc.addTrack(player.audio)
    video_sender = pc.addTrack(player.video)

    await pc.setLocalDescription(await pc.createOffer())
    answer = await post(push_url,pc.localDescription.sdp)
    await pc.setRemoteDescription(RTCSessionDescription(sdp=answer,type='answer'))

    await player.video.event.wait()
    await asyncio.sleep(4)


##########################################
# os.environ['MKL_SERVICE_FORCE_INTEL'] = '1'
# os.environ['MULTIPROCESSING_METHOD'] = 'forkserver'                                                    
if __name__ == '__main__':
    sys.path.append('./wav2lip')
    mp.set_start_method('spawn')
    parser = argparse.ArgumentParser()
    parser.add_argument('--pose', type=str, default="data/data_kf.json", help="transforms.json, pose source")
    parser.add_argument('--au', type=str, default="data/au.csv", help="eye blink area")
    parser.add_argument('--torso_imgs', type=str, default="", help="torso images path")

    parser.add_argument('-O', action='store_true', help="equals --fp16 --cuda_ray --exp_eye")

    parser.add_argument('--data_range', type=int, nargs='*', default=[0, -1], help="data range to use")
    parser.add_argument('--workspace', type=str, default='data/video')
    parser.add_argument('--seed', type=int, default=0)

    ### training options
    parser.add_argument('--ckpt', type=str, default='data/pretrained/ngp_kf.pth')
   
    parser.add_argument('--num_rays', type=int, default=4096 * 16, help="num rays sampled per image for each training step")
    parser.add_argument('--cuda_ray', action='store_true', help="use CUDA raymarching instead of pytorch")
    parser.add_argument('--max_steps', type=int, default=16, help="max num steps sampled per ray (only valid when using --cuda_ray)")
    parser.add_argument('--num_steps', type=int, default=16, help="num steps sampled per ray (only valid when NOT using --cuda_ray)")
    parser.add_argument('--upsample_steps', type=int, default=0, help="num steps up-sampled per ray (only valid when NOT using --cuda_ray)")
    parser.add_argument('--update_extra_interval', type=int, default=16, help="iter interval to update extra status (only valid when using --cuda_ray)")
    parser.add_argument('--max_ray_batch', type=int, default=4096, help="batch size of rays at inference to avoid OOM (only valid when NOT using --cuda_ray)")

    ### loss set
    parser.add_argument('--warmup_step', type=int, default=10000, help="warm up steps")
    parser.add_argument('--amb_aud_loss', type=int, default=1, help="use ambient aud loss")
    parser.add_argument('--amb_eye_loss', type=int, default=1, help="use ambient eye loss")
    parser.add_argument('--unc_loss', type=int, default=1, help="use uncertainty loss")
    parser.add_argument('--lambda_amb', type=float, default=1e-4, help="lambda for ambient loss")

    ### network backbone options
    parser.add_argument('--fp16', action='store_true', help="use amp mixed precision training")
    
    parser.add_argument('--bg_img', type=str, default='white', help="background image")
    parser.add_argument('--fbg', action='store_true', help="frame-wise bg")
    parser.add_argument('--exp_eye', action='store_true', help="explicitly control the eyes")
    parser.add_argument('--fix_eye', type=float, default=-1, help="fixed eye area, negative to disable, set to 0-0.3 for a reasonable eye")
    parser.add_argument('--smooth_eye', action='store_true', help="smooth the eye area sequence")

    parser.add_argument('--torso_shrink', type=float, default=0.8, help="shrink bg coords to allow more flexibility in deform")

    ### dataset options
    parser.add_argument('--color_space', type=str, default='srgb', help="Color space, supports (linear, srgb)")
    parser.add_argument('--preload', type=int, default=0, help="0 means load data from disk on-the-fly, 1 means preload to CPU, 2 means GPU.")
    # (the default value is for the fox dataset)
    parser.add_argument('--bound', type=float, default=1, help="assume the scene is bounded in box[-bound, bound]^3, if > 1, will invoke adaptive ray marching.")
    parser.add_argument('--scale', type=float, default=4, help="scale camera location into box[-bound, bound]^3")
    parser.add_argument('--offset', type=float, nargs='*', default=[0, 0, 0], help="offset of camera location")
    parser.add_argument('--dt_gamma', type=float, default=1/256, help="dt_gamma (>=0) for adaptive ray marching. set to 0 to disable, >0 to accelerate rendering (but usually with worse quality)")
    parser.add_argument('--min_near', type=float, default=0.05, help="minimum near distance for camera")
    parser.add_argument('--density_thresh', type=float, default=10, help="threshold for density grid to be occupied (sigma)")
    parser.add_argument('--density_thresh_torso', type=float, default=0.01, help="threshold for density grid to be occupied (alpha)")
    parser.add_argument('--patch_size', type=int, default=1, help="[experimental] render patches in training, so as to apply LPIPS loss. 1 means disabled, use [64, 32, 16] to enable")

    parser.add_argument('--init_lips', action='store_true', help="init lips region")
    parser.add_argument('--finetune_lips', action='store_true', help="use LPIPS and landmarks to fine tune lips region")
    parser.add_argument('--smooth_lips', action='store_true', help="smooth the enc_a in a exponential decay way...")

    parser.add_argument('--torso', action='store_true', help="fix head and train torso")
    parser.add_argument('--head_ckpt', type=str, default='', help="head model")

    ### GUI options
    parser.add_argument('--gui', action='store_true', help="start a GUI")
    parser.add_argument('--W', type=int, default=450, help="GUI width")
    parser.add_argument('--H', type=int, default=450, help="GUI height")
    parser.add_argument('--radius', type=float, default=3.35, help="default GUI camera radius from center")
    parser.add_argument('--fovy', type=float, default=21.24, help="default GUI camera fovy")
    parser.add_argument('--max_spp', type=int, default=1, help="GUI rendering max sample per pixel")

    ### else
    parser.add_argument('--att', type=int, default=2, help="audio attention mode (0 = turn off, 1 = left-direction, 2 = bi-direction)")
    parser.add_argument('--aud', type=str, default='', help="audio source (empty will load the default, else should be a path to a npy file)")
    parser.add_argument('--emb', action='store_true', help="use audio class + embedding instead of logits")

    parser.add_argument('--ind_dim', type=int, default=4, help="individual code dim, 0 to turn off")
    parser.add_argument('--ind_num', type=int, default=10000, help="number of individual codes, should be larger than training dataset size")

    parser.add_argument('--ind_dim_torso', type=int, default=8, help="individual code dim, 0 to turn off")

    parser.add_argument('--amb_dim', type=int, default=2, help="ambient dimension")
    parser.add_argument('--part', action='store_true', help="use partial training data (1/10)")
    parser.add_argument('--part2', action='store_true', help="use partial training data (first 15s)")

    parser.add_argument('--train_camera', action='store_true', help="optimize camera pose")
    parser.add_argument('--smooth_path', action='store_true', help="brute-force smooth camera pose trajectory with a window size")
    parser.add_argument('--smooth_path_window', type=int, default=7, help="smoothing window size")

    # asr
    parser.add_argument('--asr', action='store_true', help="load asr for real-time app")
    parser.add_argument('--asr_wav', type=str, default='', help="load the wav and use as input")
    parser.add_argument('--asr_play', action='store_true', help="play out the audio")

    #parser.add_argument('--asr_model', type=str, default='deepspeech')
    parser.add_argument('--asr_model', type=str, default='cpierse/wav2vec2-large-xlsr-53-esperanto') #
    # parser.add_argument('--asr_model', type=str, default='facebook/wav2vec2-large-960h-lv60-self')
    # parser.add_argument('--asr_model', type=str, default='facebook/hubert-large-ls960-ft')

    parser.add_argument('--asr_save_feats', action='store_true')
    # audio FPS
    parser.add_argument('--fps', type=int, default=50)
    # sliding window left-middle-right length (unit: 20ms)
    parser.add_argument('-l', type=int, default=10)
    parser.add_argument('-m', type=int, default=8)
    parser.add_argument('-r', type=int, default=10)

    parser.add_argument('--fullbody', action='store_true', help="fullbody human")
    parser.add_argument('--fullbody_img', type=str, default='data/fullbody/img')
    parser.add_argument('--fullbody_width', type=int, default=580)
    parser.add_argument('--fullbody_height', type=int, default=1080)
    parser.add_argument('--fullbody_offset_x', type=int, default=0)
    parser.add_argument('--fullbody_offset_y', type=int, default=0)

    #musetalk opt
    parser.add_argument('--avatar_id', type=str, default='avator_1')
    parser.add_argument('--bbox_shift', type=int, default=5)
    parser.add_argument('--batch_size', type=int, default=16)

    # parser.add_argument('--customvideo', action='store_true', help="custom video")
    # parser.add_argument('--customvideo_img', type=str, default='data/customvideo/img')
    # parser.add_argument('--customvideo_imgnum', type=int, default=1)

    parser.add_argument('--customvideo_config', type=str, default='')

    parser.add_argument('--tts', type=str, default='edgetts') #xtts gpt-sovits cosyvoice
    parser.add_argument('--REF_FILE', type=str, default=None)
    parser.add_argument('--REF_TEXT', type=str, default=None)
    parser.add_argument('--TTS_SERVER', type=str, default='http://127.0.0.1:9880') # http://localhost:9000
    # parser.add_argument('--CHARACTER', type=str, default='test')
    # parser.add_argument('--EMOTION', type=str, default='default')

    parser.add_argument('--model', type=str, default='ernerf') #musetalk wav2lip

    parser.add_argument('--transport', type=str, default='rtcpush') #rtmp webrtc rtcpush
    parser.add_argument('--push_url', type=str, default='http://localhost:1985/rtc/v1/whip/?app=live&stream=livestream') #rtmp://localhost/live/livestream

    parser.add_argument('--max_session', type=int, default=1)  #multi session count
    parser.add_argument('--listenport', type=int, default=8010)

    opt = parser.parse_args()
    #app.config.from_object(opt)
    #print(app.config)
    opt.customopt = []
    if opt.customvideo_config!='':
        with open(opt.customvideo_config,'r') as file:
            opt.customopt = json.load(file)

    if opt.model == 'ernerf':       
        from nerfreal import NeRFReal,load_model,load_avatar
        model = load_model(opt)

        # we still need test_loader to provide audio features for testing.
        # for k in range(opt.max_session):
        #     opt.sessionid=k
        #     nerfreal = NeRFReal(opt, trainer, test_loader,audio_processor,audio_model)
        #     nerfreals.append(nerfreal)
    elif opt.model == 'musetalk':
        from musereal import MuseReal,load_model,load_avatar,warm_up
        logger.info(opt)
        model = load_model()
        warm_up(opt.batch_size,model)      
        # for k in range(opt.max_session):
        #     opt.sessionid=k
        #     nerfreal = MuseReal(opt,audio_processor,vae, unet, pe,timesteps)
        #     nerfreals.append(nerfreal)
    elif opt.model == 'wav2lip':
        from lipreal import LipReal,load_model,load_avatar,warm_up
        logger.info(opt)
        model = load_model("./models/wav2lip.pth")
        warm_up(opt.batch_size,model,256)
        # for k in range(opt.max_session):
        #     opt.sessionid=k
        #     nerfreal = LipReal(opt,model)
        #     nerfreals.append(nerfreal)
    elif opt.model == 'ultralight':
        from lightreal import LightReal,load_model,load_avatar,warm_up
        logger.info(opt)
        model = load_model(opt)
        avatar = load_avatar(opt.avatar_id)
        warm_up(opt.batch_size,avatar,160)

    if opt.transport=='rtmp':
        thread_quit = Event()
        nerfreals[0] = build_nerfreal(0)
        rendthrd = Thread(target=nerfreals[0].render,args=(thread_quit,))
        rendthrd.start()

    #############################################################################
    appasync = web.Application(client_max_size=10 * 1024 * 1024)
    appasync.on_shutdown.append(on_shutdown)
    # appasync.router.add_post("/offer", offer)
    appasync.router.add_post("/human", human)
    appasync.router.add_post("/humanaudio", humanaudio)
    appasync.router.add_post("/set_audiotype", set_audiotype)
    appasync.router.add_post("/record", record)
    appasync.router.add_post("/is_speaking", is_speaking)
    appasync.router.add_post("/start", start)
    appasync.router.add_post("/stop", stop)
    appasync.router.add_post("/is_start", is_start)
    appasync.router.add_post("/check_model", check_model)
    appasync.router.add_post("/upload", upload)
    appasync.router.add_post("/upload_sound", upload_sound)
    appasync.router.add_static('/',path='web')

    # Configure default CORS settings.
    cors = aiohttp_cors.setup(appasync, defaults={
            "*": aiohttp_cors.ResourceOptions(
                allow_credentials=True,
                expose_headers="*",
                allow_headers="*",
            )
        })
    # Configure CORS on all routes.
    for route in list(appasync.router.routes()):
        cors.add(route)

    pagename='webrtcapi.html'
    if opt.transport=='rtmp':
        pagename='echoapi.html'
    elif opt.transport=='rtcpush':
        pagename='rtcpushapi.html'
    logger.info('start http server; http://<serverip>:'+str(opt.listenport)+'/'+pagename)
    def run_server(runner):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(runner.setup())
        site = web.TCPSite(runner, '0.0.0.0', opt.listenport)
        loop.run_until_complete(site.start())
        # if opt.transport=='rtcpush':
        #     for k in range(opt.max_session):
        #         push_url = opt.push_url+str(k)
        #         loop.run_until_complete(run(push_url,k))
        loop.run_forever()    
    #Thread(target=run_server, args=(web.AppRunner(appasync),)).start()
    run_server(web.AppRunner(appasync))

    #app.on_shutdown.append(on_shutdown)
    #app.router.add_post("/offer", offer)

    # print('start websocket server')
    # server = pywsgi.WSGIServer(('0.0.0.0', 8000), app, handler_class=WebSocketHandler)
    # server.serve_forever()
    
    
