import asyncio
import logging
from astrbot.api.star import Star, register
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import Plain
from astrbot.api.all import Context

logger = logging.getLogger("astrbot")

PLUGIN_ID = "astrbot_plugin_game_vote"


def _load_plugin_config(context: Context) -> dict:
    """兼容不同版本的 AstrBot，从插件管理器中获取本插件的配置。"""
    cfg = None

    plugin_manager = getattr(context, "plugin_manager", None)
    if plugin_manager and hasattr(plugin_manager, "get_plugin_config"):
        raw = plugin_manager.get_plugin_config(PLUGIN_ID)
        if raw:
            if isinstance(raw, dict):
                cfg = raw
            elif hasattr(raw, "config"):
                cfg = raw.config
            elif hasattr(raw, "get_config"):
                try:
                    cfg = raw.get_config()
                except Exception:
                    pass

    # 兜底：旧版本可能只能拿到整体配置
    if not cfg and hasattr(context, "get_config"):
        possible = context.get_config()
        if isinstance(possible, dict):
            cfg = possible.get(PLUGIN_ID)

    if not cfg:
        cfg = {}

    logger.info(f"[GameVote] DEBUG - 插件配置载入结果: {cfg}")
    return cfg


@register(PLUGIN_ID, "AntGent", "指令式组队投票插件", "1.0.7", "https://github.com/AntGent/astrbot_plugin_game_vote")
class GameVotePlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.active_votes = {}

    @filter.command("有没有人玩")
    async def start_vote(self, event: AstrMessageEvent, game_name: str, max_players: int):
        origin_id = event.unified_msg_origin

        if origin_id in self.active_votes:
            yield event.plain_result(f"⚠️ 这里已经有一个【{self.active_votes[origin_id]['game_name']}】的投票在进行了。")
            return

        try:
            max_players = int(max_players)
            if max_players <= 1:
                yield event.plain_result("❌ 人数上限必须大于1。")
                return
        except ValueError:
            yield event.plain_result("❌ 人数必须是有效的数字。")
            return

        cfg = _load_plugin_config(self.context)
        timeout = 300
        raw_val = cfg.get("default_timeout")
        if raw_val is not None:
            try:
                timeout = max(5, int(raw_val))
                logger.info(f"[GameVote] 使用配置倒计时: {timeout} 秒")
            except Exception:
                logger.warning("[GameVote] default_timeout 不是有效数字，使用默认值 300")

        sender = event.get_sender_name()

        self.active_votes[origin_id] = {
            "game_name": game_name,
            "max_players": max_players,
            "players": [sender],
            "timer_task": None
        }

        task = asyncio.create_task(self._timeout_task(event, origin_id, timeout))
        self.active_votes[origin_id]["timer_task"] = task

        yield event.plain_result(
            f"🎮 {sender} 发起了游戏组队！\n"
            f"项目：【{game_name}】\n"
            f"目标：{max_players} 人\n"
            f"输入 /玩 即可加入队伍 (1/{max_players})\n"
            f"⏰ 倒计时 {timeout} 秒。"
        )

    @filter.command("玩")
    async def join_vote(self, event: AstrMessageEvent):
        origin_id = event.unified_msg_origin

        if origin_id not in self.active_votes:
            yield event.plain_result("💡 当前没有正在进行的组队。发送“/有没有人玩 游戏名 人数”发起一个吧！")
            return

        vote = self.active_votes[origin_id]
        sender = event.get_sender_name()

        if sender in vote["players"]:
            yield event.plain_result(f"@{sender} 你已经在队伍里啦 ({len(vote['players'])}/{vote['max_players']})")
            return

        vote["players"].append(sender)
        curr_count = len(vote["players"])
        max_count = vote["max_players"]

        if curr_count >= max_count:
            if vote["timer_task"]:
                vote["timer_task"].cancel()

            p_list = "\n- ".join(vote["players"])
            game_name = vote["game_name"]
            del self.active_votes[origin_id]

            yield event.plain_result(f"✅ 人齐啦！【{game_name}】组队成功！\n名单如下：\n- {p_list}")
        else:
            yield event.plain_result(f"📝 {sender} 加入了队伍 ({curr_count}/{max_count})")

    @filter.command("都有谁")
    async def list_players(self, event: AstrMessageEvent):
        origin_id = event.unified_msg_origin

        if origin_id not in self.active_votes:
            yield event.plain_result("💡 当前没有正在进行的投票。")
            return

        vote = self.active_votes[origin_id]
        game_name = vote["game_name"]
        curr_count = len(vote["players"])
        max_count = vote["max_players"]
        p_list = "\n- ".join(vote["players"])

        yield event.plain_result(
            f"🔍 【{game_name}】当前组队情况：\n"
            f"进度：{curr_count}/{max_count}\n"
            f"成员：\n- {p_list}"
        )

    async def _timeout_task(self, event: AstrMessageEvent, origin_id: str, delay: int):
        try:
            await asyncio.sleep(delay)
            if origin_id in self.active_votes:
                vote = self.active_votes[origin_id]
                p_list = ", ".join(vote["players"])
                count = len(vote["players"])
                game_name = vote["game_name"]

                msg_content = [Plain(text=f"⏰ 【{game_name}】组队倒计时结束。\n最终集结 {count} 人：{p_list}")]
                await self.context.send_message(event.unified_msg_origin, msg_content)

                del self.active_votes[origin_id]
        except asyncio.CancelledError:
            pass
