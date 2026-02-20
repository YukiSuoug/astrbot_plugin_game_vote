import asyncio
import logging
from astrbot.api.star import Star, register
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import Plain
from astrbot.api.all import Context
from astrbot.core.config.astrbot_config import AstrBotConfig

logger = logging.getLogger("astrbot")
PLUGIN_ID = "astrbot_plugin_game_vote"


@register(
    PLUGIN_ID,
    "AntGent",
    "指令式组队投票插件",
    "1.1.1",
    "https://github.com/AntGent/astrbot_plugin_game_vote",
)
class GameVotePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.active_votes = {}  # {umo: {...}}

    def _get_timeout(self) -> int:
        """获取配置中的超时时间"""
        try:
            val = int(self.config.get("default_timeout", 300))
            return max(5, val)
        except Exception:
            return 300

    @filter.command("有没有人玩")
    async def start_vote(self, event: AstrMessageEvent, game_name: str, max_players: int):
        origin_id = event.unified_msg_origin

        if origin_id in self.active_votes:
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
        
        # 调试日志：确认倒计时启动
        logger.info(f"[GameVote] {sender} 发起投票，倒计时设定为 {timeout} 秒")

        # 创建任务并存储，防止被垃圾回收
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
            # 人满结算
            if vote["timer_task"]:
                vote["timer_task"].cancel()

            members = "\n- ".join(vote["players"])
            game = vote["game_name"]
            del self.active_votes[origin_id]

            yield event.plain_result(f"✅ 人齐啦！【{game}】组队成功！\n名单如下：\n- {members}")
        else:
            # 修改：增加了 @前缀
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
        """倒计时任务，时间到后自动结算"""
        try:
            # 等待指定时间
            await asyncio.sleep(delay)

            # 检查投票是否存在
            if origin_id in self.active_votes:
                vote = self.active_votes[origin_id]
                logger.info(f"[GameVote] 倒计时结束，自动结算：{vote['game_name']}")
                
                members = ", ".join(vote["players"])
                count = len(vote["players"])
                
                # 构建消息组件
                msg = [
                    Plain(text=f"⏰ 【{vote['game_name']}】倒计时结束。\n最终集结 {count} 人：{members}")
                ]
                
                # 发送消息
                await self.context.send_message(origin_id, msg)
                
                # 清理数据
                del self.active_votes[origin_id]
                
        except asyncio.CancelledError:
            # 任务被取消（说明人齐了），不需要做任何事
            pass
        except Exception as e:
            logger.error(f"[GameVote] 倒计时任务出错: {e}")
