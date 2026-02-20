import asyncio
import logging
from astrbot.api.star import Star, register
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.all import Context
from astrbot.core.config.astrbot_config import AstrBotConfig

# --- 核心修复：完全参照你提供的 RestartPlugin 源码导入正确的库 ---
from astrbot.core.message.components import Plain
from astrbot.core.message.message_event_result import MessageChain

logger = logging.getLogger("astrbot")
PLUGIN_ID = "astrbot_plugin_game_vote"

@register(
    PLUGIN_ID,
    "AntGent",
    "指令式组队投票插件",
    "1.1.3",
    "https://github.com/AntGent/astrbot_plugin_game_vote",
)
class GameVotePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.active_votes = {}  # {umo: {...}}

    def _get_timeout(self) -> int:
        """获取超时时间"""
        try:
            val = self.config.get("default_timeout", 300)
            return max(5, int(val))
        except Exception:
            return 300

    @filter.command("有没有人玩")
    async def start_vote(self, event: AstrMessageEvent, game_name: str, max_players: int):
        origin_id = event.unified_msg_origin

        if origin_id in self.active_votes:
            # 这里的 plain_result 是 event 快捷回复，不受影响
            yield event.plain_result(f"⚠️ 这里已经有一个【{self.active_votes[origin_id]['game_name']}】的投票在进行了。")
            return

        try:
            max_players = int(max_players)
            if max_players <= 1:
                yield event.plain_result("❌ 人数上限必须大于 1。")
                return
        except ValueError:
            yield event.plain_result("❌ 人数必须是有效数字。")
            return

        sender = event.get_sender_name()
        timeout = self._get_timeout()
        
        logger.info(f"[GameVote] 启动新投票: {game_name}, 倒计时: {timeout}秒")

        task = asyncio.create_task(self._timeout_task(event, origin_id, timeout))
        
        self.active_votes[origin_id] = {
            "game_name": game_name,
            "max_players": max_players,
            "players": [sender],
            "timer_task": task,
        }

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
        curr = len(vote["players"])
        goal = vote["max_players"]

        if curr >= goal:
            if vote["timer_task"]:
                vote["timer_task"].cancel()

            members = "\n- ".join(vote["players"])
            game = vote["game_name"]
            del self.active_votes[origin_id]

            yield event.plain_result(f"✅ 人齐啦！【{game}】组队成功！\n名单如下：\n- {members}")
        else:
            yield event.plain_result(f"@{sender} 加入了队伍 ({curr}/{goal})")

    @filter.command("都有谁")
    async def list_players(self, event: AstrMessageEvent):
        origin_id = event.unified_msg_origin

        if origin_id not in self.active_votes:
            yield event.plain_result("💡 当前没有正在进行的投票。")
            return

        vote = self.active_votes[origin_id]
        members = "\n- ".join(vote["players"])

        yield event.plain_result(
            f"🔍 【{vote['game_name']}】当前进度：{len(vote['players'])}/{vote['max_players']}\n"
            f"成员：\n- {members}"
        )

    async def _timeout_task(self, event: AstrMessageEvent, origin_id: str, delay: int):
        try:
            await asyncio.sleep(delay)
            
            vote = self.active_votes.get(origin_id)
            if not vote:
                return

            logger.info(f"[GameVote] 投票超时结算: {vote['game_name']}")
            
            members = ", ".join(vote["players"])
            count = len(vote["players"])
            game_name = vote["game_name"]
            
            # --- 关键修复：构造 MessageChain 对象 ---
            # 直接传入列表会导致 'list object has no attribute chain' 错误
            chain = MessageChain([
                Plain(text=f"⏰ 【{game_name}】倒计时结束。\n最终集结 {count} 人：{members}")
            ])
            
            # 使用正确的参数发送
            await self.context.send_message(origin_id, chain)
            
            if origin_id in self.active_votes:
                del self.active_votes[origin_id]
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[GameVote] 倒计时错误: {e}")
