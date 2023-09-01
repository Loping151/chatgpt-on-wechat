# encoding:utf-8

import io
import json
import os

import re
import webuiapi
import langid
from bridge.bridge import Bridge
import plugins
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from config import conf
from plugins import *


@plugins.register(name="sdwebui", desc="利用stable-diffusion webui来画图", version="2.1", author="lanvent")
class SDWebUI(Plugin):
    def __init__(self):
        super().__init__()
        curdir = os.path.dirname(__file__)
        config_path = os.path.join(curdir, "config.json")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                self.rules = config["rules"]
                defaults = config["defaults"]
                self.default_params = defaults["params"]
                self.default_options = defaults["options"]
                self.start_args = config["start"]
                self.api = webuiapi.WebUIApi(**self.start_args)
            self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
            logger.info("[SD] inited")
        except Exception as e:
            if isinstance(e, FileNotFoundError):
                logger.warn(f"[SD] init failed, {config_path} not found, ignore or see https://github.com/zhayujie/chatgpt-on-wechat/tree/master/plugins/sdwebui .")
            else:
                logger.warn("[SD] init failed, ignore or see https://github.com/zhayujie/chatgpt-on-wechat/tree/master/plugins/sdwebui .")
            raise e

    def on_handle_context(self, e_context: EventContext):

        if e_context['context'].type != ContextType.IMAGE_CREATE:
            return
        channel = e_context['channel']
        if ReplyType.IMAGE in channel.NOT_SUPPORT_REPLYTYPE:
            return

        logger.debug("[SD] on_handle_context. content: %s" %e_context['context'].content)

        logger.info("[SD] image_query={}".format(e_context['context'].content))
        reply = Reply()
        try:
            content = e_context['context'].content[:]
            # 解析用户输入 如"横版 高清 二次元:cat"
            if ":" in content:
                keywords, prompt = content.split(":", 1)
            else:
                keywords = content
                prompt = ""

            keywords = keywords.split()
            unused_keywords = []
            if "help" in keywords or "帮助" in keywords:
                reply.type = ReplyType.INFO
                reply.content = self.get_help_text(verbose = True)
            else:
                rule_params = {}
                rule_options = {}
                for keyword in keywords:
                    matched = False
                    for rule in self.rules:
                        if keyword in rule["keywords"]:
                            for key in rule["params"]:
                                rule_params[key] = rule["params"][key]
                            if "options" in rule:
                                for key in rule["options"]:
                                    rule_options[key] = rule["options"][key]
                            matched = True
                            break  # 一个关键词只匹配一个规则
                    if not matched:
                        unused_keywords.append(keyword)
                        logger.info("[SD] keyword not matched: %s" % keyword)

                params = {**self.default_params, **rule_params}
                options = {**self.default_options, **rule_options}
                params["prompt"] = params.get("prompt", "")
                if unused_keywords:
                    if prompt:
                        prompt += f", {', '.join(unused_keywords)}"
                    else:
                        prompt = ', '.join(unused_keywords)
                if prompt:
                    lang = langid.classify(prompt)[0]
                    if lang != "en":
                        logger.info("[SD] translate prompt from {} to en".format(lang))
                        try:
                            prompt = Bridge().fetch_translate(prompt, to_lang= "en")
                        except Exception as e:
                            logger.info("[SD] translate failed: {}".format(e))
                        logger.info("[SD] translated prompt={}".format(prompt))
                    params["prompt"] += f", {prompt}"
                if re.search(r'nsfw', prompt, re.IGNORECASE):
                    reply = Reply(ReplyType.TEXT, "你想封我号吗，朋友")
                else:
                    if len(options) > 0:
                        logger.info("[SD] cover options={}".format(options))
                        self.api.set_options(options)
                    logger.info("[SD] params={}".format(params))
                    result = self.api.txt2img(
                        **params
                    )
                    reply.type = ReplyType.IMAGE
                    b_img = io.BytesIO()
                    result.image.save(b_img, format="PNG")
                    reply.content = b_img
            e_context.action = EventAction.BREAK_PASS  # 事件结束后，跳过处理context的默认逻辑
        except Exception as e:
            reply.type = ReplyType.ERROR
            reply.content = "[SD] "+str(e)
            logger.error("[SD] exception: %s" % e)
            e_context.action = EventAction.CONTINUE  # 事件继续，交付给下个插件或默认逻辑
        finally:
            e_context['reply'] = reply

    def get_help_text(self, verbose = False, **kwargs):
        if not conf().get('image_create_prefix'):
            return "画图功能未启用"
        else:
            trigger = conf()['image_create_prefix'][0]
        help_text = "利用stable-diffusion来画图。\n"
        if not verbose:
            return help_text

        help_text += f"使用方法:\n使用\"{trigger}[模型名称] [关键词2]...:prompt\"的格式作画，如\"{trigger}AOM3B2 高清:catgirl\"\n"
        help_text += f"151提醒您: 请使用英语的冒号, 否则不识别为关键词. 使用中文prompt时, 会造成我的百度翻译额度消费, 请慎用. 模型名称, :prompt可以不写\n"
        help_text += f"151重点强调: 请不要试图使用某四个字母的关键词和类似关键字, 以防主人受到法律制裁.\n"
        help_text += "目前可用关键词和模型: \n"
        for rule in self.rules:
            keywords = [f"[{keyword}]" for keyword in rule['keywords']]
            help_text += f"{','.join(keywords)}"
            if "desc" in rule:
                help_text += f"-{rule['desc']}\n"
            else:
                help_text += "\n"
        return help_text
