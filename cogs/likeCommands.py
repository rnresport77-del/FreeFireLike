import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
from datetime import datetime
import json
import os
import asyncio
from dotenv import load_dotenv

load_dotenv()
API_URL = os.getenv("API_URL")
CONFIG_FILE = "like_channels.json"

class LikeCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.api_host = API_URL
        self.config_data = self.load_config()
        self.cooldowns = {}
        self.session = aiohttp.ClientSession()

    def load_config(self):
        default_config = {"servers": {}}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    loaded_config = json.load(f)
                    loaded_config.setdefault("servers", {})
                    return loaded_config
            except json.JSONDecodeError:
                print(
                    f"WARNING: The configuration file '{CONFIG_FILE}' is corrupt or empty. Resetting to default configuration."
                )
        self.save_config(default_config)
        return default_config

    def save_config(self, config_to_save=None):
        data_to_save = config_to_save if config_to_save is not None else self.config_data
        temp_file = CONFIG_FILE + ".tmp"
        with open(temp_file, "w") as f:
            json.dump(data_to_save, f, indent=4)
        os.replace(temp_file, CONFIG_FILE)

    async def check_channel(self, ctx, mode="like"):
        """mode = 'like' or 'auto_like'"""
        if ctx.guild is None:
            return True
        guild_id = str(ctx.guild.id)
        key = "like_channels" if mode == "like" else "auto_like_channels"
        allowed_channels = self.config_data["servers"].get(guild_id, {}).get(key, [])
        return not allowed_channels or str(ctx.channel.id) in allowed_channels

    async def cog_load(self):
        pass

    # =========================
    # /setlikechannel
    # =========================
    @commands.hybrid_command(
        name="setlikechannel", description="Sets the channels where the /like command is allowed."
    )
    @commands.has_permissions(administrator=True)
    @app_commands.describe(channel="The channel to allow/disallow the /like command in.")
    async def set_like_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        if ctx.guild is None:
            await ctx.send("This command can only be used in a server.", ephemeral=True)
            return

        guild_id = str(ctx.guild.id)
        server_config = self.config_data["servers"].setdefault(guild_id, {})
        like_channels = server_config.setdefault("like_channels", [])

        channel_id_str = str(channel.id)

        if channel_id_str in like_channels:
            like_channels.remove(channel_id_str)
            self.save_config()
            await ctx.send(
                f"✅ Channel {channel.mention} has been **removed** from allowed channels for /like commands.",
                ephemeral=True,
            )
        else:
            like_channels.append(channel_id_str)
            self.save_config()
            await ctx.send(
                f"✅ Channel {channel.mention} is now **allowed** for /like commands.",
                ephemeral=True,
            )

    # =========================
    # /auto_like setup_channel
    # =========================
    @commands.hybrid_group(name="auto_like", description="Auto Like system commands")
    async def auto_like_group(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await ctx.send("⚠️ Use `/auto_like setup_channel` or `/auto_like uid server`.", ephemeral=True)

    @auto_like_group.command(name="setup_channel", description="Sets the channels where /auto_like is allowed.")
    @commands.has_permissions(administrator=True)
    @app_commands.describe(channel="The channel to allow/disallow the /auto_like command in.")
    async def setup_auto_like_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        guild_id = str(ctx.guild.id)
        server_config = self.config_data["servers"].setdefault(guild_id, {})
        auto_like_channels = server_config.setdefault("auto_like_channels", [])

        channel_id_str = str(channel.id)

        if channel_id_str in auto_like_channels:
            auto_like_channels.remove(channel_id_str)
            self.save_config()
            await ctx.send(
                f"❌ Channel {channel.mention} has been **removed** from allowed channels for /auto_like.",
                ephemeral=True,
            )
        else:
            auto_like_channels.append(channel_id_str)
            self.save_config()
            await ctx.send(
                f"✅ Channel {channel.mention} is now **allowed** for /auto_like commands.",
                ephemeral=True,
            )

    # =========================
    # /like command
    # =========================
    @commands.hybrid_command(name="like", description="Sends likes to a Free Fire player")
    @app_commands.describe(uid="Player UID", server="Server name")
    async def like_command(self, ctx: commands.Context, server: str = None, uid: str = None):
        await self._process_like(ctx, server, uid, mode="like")

    # =========================
    # /auto_like command
    # =========================
    @auto_like_group.command(name="send", description="Auto Like command (same as /like)")
    @app_commands.describe(uid="Player UID", server="Server name")
    async def auto_like_command(self, ctx: commands.Context, server: str = None, uid: str = None):
        await self._process_like(ctx, server, uid, mode="auto_like")

    # =========================
    # LIKE PROCESS (Shared)
    # =========================
    async def _process_like(self, ctx, server, uid, mode="like"):
        is_slash = ctx.interaction is not None

        if uid is None or server is None:
            return await ctx.send("⚠️ UID and server are required.", delete_after=10)

        if not await self.check_channel(ctx, mode=mode):
            msg = f"This command is not available in this channel. Please use it in an authorized {mode} channel."
            if is_slash:
                await ctx.response.send_message(msg, ephemeral=True)
            else:
                await ctx.reply(msg, mention_author=False)
            return

        # cooldown per user
        user_id = ctx.author.id
        cooldown = 30
        if user_id in self.cooldowns:
            last_used = self.cooldowns[user_id]
            remaining = cooldown - (datetime.now() - last_used).seconds
            if remaining > 0:
                await ctx.send(
                    f"Please wait {remaining} seconds before using this command again.",
                    ephemeral=is_slash,
                )
                return
        self.cooldowns[user_id] = datetime.now()

        # UID Validation
        if not uid.isdigit() or len(uid) < 6:
            await ctx.reply("Invalid UID. It must contain only numbers and be at least 6 characters long.",
                            mention_author=False, ephemeral=is_slash)
            return

        try:
            async with ctx.typing():
                url = f"{self.api_host}/like?uid={uid}&server={server}"
                print(url)
                async with self.session.get(url) as response:
                    if response.status == 404:
                        await self._send_player_not_found(ctx, uid)
                        return

                    if response.status != 200:
                        await self._send_api_error(ctx)
                        return

                    data = await response.json()
                    # success / fail embed একইভাবে যাবে
                    if data.get("status") == 1:
                        embed = discord.Embed(
                            title=f"👑 Panther Corporation ({mode.upper()}) 👑",
                            description="💖 **Likes delivered successfully!**",
                            color=0x2ECC71,
                            timestamp=datetime.now(),
                        )
                        embed.add_field(
                            name="👤 Player Info",
                            value=f"```UID  : {uid}\nName : {data.get('player','Unknown')}```",
                            inline=True,
                        )
                        embed.add_field(
                            name="🌍 Server Region",
                            value=f"```{server.upper()} Server```",
                            inline=True,
                        )
                        before = data.get("likes_before", "N/A")
                        after = data.get("likes_after", "N/A")
                        added = data.get("likes_added", 0)
                        embed.add_field(
                            name="📊 Like Status",
                            value=f"```Before: {before} likes\nAfter : {after} likes\nAdded : {added} likes```",
                            inline=False,
                        )
                                                embed.add_field(
                            name="⚡ Execution Info",
                            value=f"👤 Requested by: {ctx.author.mention}\n🕒 Time: <t:{int(datetime.now().timestamp())}:R>",
                            inline=False,
                        )

                        embed.set_image(url="https://imgur.com/mXr0UDF.gif")
                        embed.set_footer(
                            text="🔰Developer: ! 1n Only Leo"
                        )
                        embed.description += "\n🔗 JOIN : https://discord.gg/dHkkwvCkWt"
                        embed.set_footer(text=f"Requested by {ctx.author}")
                    else:
                        embed = discord.Embed(
                            title="❌ LIKE FAILED",
                            description="⚠️ This UID has already received the maximum likes today.",
                            color=0xE74C3C,
                            timestamp=datetime.now(),
                        )
                        embed.set_footer(text=f"Requested by {ctx.author}")

                    await ctx.send(embed=embed, mention_author=True, ephemeral=is_slash)

        except asyncio.TimeoutError:
            await self._send_error_embed(ctx, "Timeout", "The server took too long to respond.", ephemeral=is_slash)
        except Exception as e:
            print(f"Unexpected error in {mode}_command: {e}")
            await self._send_error_embed(ctx, "Critical Error", "Unexpected error occurred.", ephemeral=is_slash)

    # =========================
    # Helper Embeds
    # =========================
    async def _send_player_not_found(self, ctx, uid):
        embed = discord.Embed(
            title="Player Not Found",
            description=f"The UID {uid} does not exist or is not accessible.",
            color=0xE74C3C,
        )
        await ctx.send(embed=embed, ephemeral=True)

    async def _send_api_error(self, ctx):
        embed = discord.Embed(
            title="⚠️ Service Unavailable",
            description="The Free Fire API is not responding at the moment.",
            color=0xF39C12,
        )
        await ctx.send(embed=embed, ephemeral=True)

    async def _send_error_embed(self, ctx, title, description, ephemeral=True):
        embed = discord.Embed(
            title=f"❌ {title}",
            description=description,
            color=discord.Color.red(),
            timestamp=datetime.now(),
        )
        await ctx.send(embed=embed, ephemeral=ephemeral)

    def cog_unload(self):
        self.bot.loop.create_task(self.session.close())

async def setup(bot):
    await bot.add_cog(LikeCommands(bot))
