import time
import os
from basereal import BaseReal
from logger import logger

def llm_response(message,nerfreal:BaseReal):
    start = time.perf_counter()
    from openai import OpenAI
    client = OpenAI(
        # 此为默认路径，您可根据业务所在地域进行配置
        base_url="https://ark.cn-beijing.volces.com/api/v3/bots",
        # 从环境变量中获取您的 API Key。此为默认方式，您可根据需要进行修改
        api_key="3b10c0a3-faa4-4219-a07c-071268eb9ecc",

        # # 如果您没有配置环境变量，请在此处用您的API Key进行替换
        # api_key=os.getenv("DASHSCOPE_API_KEY"),
        # # 填写DashScope SDK的base_url
        # base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    end = time.perf_counter()
    logger.info(f"llm Time init: {end-start}s")
    completion = client.chat.completions.create(
        model="bot-20250304111658-v8z2f",
        messages=[
            # {'role': 'system', 'content': 'You are a helpful assistant.'},
                  {'role': 'user', 'content': message}],
        stream=True,
        # 通过以下设置，在流式输出的最后一行展示token使用信息
        stream_options={"include_usage": True}
    )
    result=""
    first = True
    for chunk in completion:
        if len(chunk.choices)>0:
            #print(chunk.choices[0].delta.content)
            if first:
                end = time.perf_counter()
                logger.info(f"llm Time to first chunk: {end-start}s")
                first = False
            msg = chunk.choices[0].delta.content
            # lastpos=0
            # #msglist = re.split('[,.!;:，。！?]',msg)
            # for i, char in enumerate(msg):
            #     if char in ",.!;:，。！？：；" :
            #         result = result+msg[lastpos:i+1]
            #         lastpos = i+1
            #         if len(result)>10:
            #             logger.info(result)
            #             nerfreal.put_msg_txt(result)
            #             result=""
            # result = result+msg[lastpos:]
            result = result + msg[0:]
            while len(result)>10:
                pos = 10
                logger.info(result[:pos])
                nerfreal.put_msg_txt(result[:pos])
                result = result[pos+1:]

    end = time.perf_counter()
    logger.info(f"llm Time to last chunk: {end-start}s")
    nerfreal.put_msg_txt(result)    