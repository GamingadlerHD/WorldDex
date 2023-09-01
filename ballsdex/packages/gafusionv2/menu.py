from __future__ import annotations

import discord
import asyncio
import logging
import random

from typing import TYPE_CHECKING, cast
from datetime import datetime, timedelta
from dataclasses import dataclass, field

from discord.ui import View, button, Button

from ballsdex.settings import settings
from ballsdex.core.models import Player, BallInstance, balls, Special
from ballsdex.core.utils.transformers import BallInstanceTransform
from ballsdex.packages.countryballs.countryball import CountryBall

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot
    from ballsdex.packages.gafusionv2.cog import Fusion as FusionCog

log = logging.getLogger("ballsdex.packages.fusion.menu")


class InvalidFusionOperation(Exception):
    pass


@dataclass(slots=True)
class FusingUser:
    user: discord.User | discord.Member
    player: Player
    proposal: list[BallInstance] = field(default_factory=list)
    locked: bool = False
    cancelled: bool = False
    accepted: bool = False


class FusionView(View):
    def __init__(self, fusion: FusionMenu):
        super().__init__(timeout=600)
        self.fusion = fusion
        

    async def interaction_check(self, interaction: discord.Interaction, /) -> bool:
        try:
            self.fusion._get_fusioner(interaction.user)
        except RuntimeError:
            await interaction.response.send_message(
                "You are not allowed to interact with this fusion.", ephemeral=True
            )
            return False
        else:
            return True

    @button(label="Lock proposal", emoji="\N{LOCK}", style=discord.ButtonStyle.primary)
    async def lock(self, interaction: discord.Interaction, button: Button):
        fusioner = self.fusion._get_fusioner(interaction.user)
        fuse_countryballs: list[BallInstance] = []

        for countryball in fusioner.proposal:
            await countryball.refresh_from_db()
            if countryball.player.discord_id != fusioner.player.discord_id:
                # This is a invalid mutation, the player is not the owner of the countryball
                raise InvalidFusionOperation()
            countryball.player = fusioner.player
            countryball.fusion_player = fusioner.player
            countryball.favorite = False
            fuse_countryballs.append(countryball)
        
        # check country
        fuse_country = fuse_countryballs[0].countryball
        for ball in fuse_countryballs:
            if ball.countryball != fuse_country:
                await interaction.response.send_message(
                    "Use only Countryballs from one Country", ephemeral=True
                    )
                return
        # Check if user uses 10 cb
        if len(fuse_countryballs) != 10: 
            await interaction.response.send_message(
                "You have to use 10 Countryballs to fuse", ephemeral=True
                )
            return
            
        if fusioner.locked:
            await interaction.response.send_message(
                "You have already locked your proposal!", ephemeral=True
            )
            return
        await self.fusion.lock(fusioner)
        await interaction.response.send_message(
            "Your proposal has been locked. Now confirm again to end the fusion.",
            ephemeral=True,
        )
        
    @button(label="Reset", emoji="\N{DASH SYMBOL}", style=discord.ButtonStyle.secondary)
    async def clear(self, interaction: discord.Interaction, button: Button):
        fusioner = self.fusion._get_fusioner(interaction.user)
        if fusioner.locked:
            await interaction.response.send_message(
                "You have locked your proposal, it cannot be edited! "
                "You can click the cancel button to stop the fusion instead.",
                ephemeral=True,
            )
        else:
            fusioner.proposal.clear()
            await interaction.response.send_message("Proposal cleared.", ephemeral=True)

    @button(
        label="Cancel fusion",
        emoji="\N{HEAVY MULTIPLICATION X}\N{VARIATION SELECTOR-16}",
        style=discord.ButtonStyle.danger,
    )
    async def cancel(self, interaction: discord.Interaction, button: Button):
        await self.fusion.user_cancel(self.fusion._get_fusioner(interaction.user))
        await interaction.response.send_message("Fusion has been cancelled.", ephemeral=True)


class ConfirmView(View):
    def __init__(self, fusion: FusionMenu):
        super().__init__(timeout=90)
        self.fusion = fusion

    async def interaction_check(self, interaction: discord.Interaction, /) -> bool:
        try:
            self.fusion._get_fusioner(interaction.user)
        except RuntimeError:
            await interaction.response.send_message(
                "You are not allowed to interact with this fusion.", ephemeral=True
            )
            return False
        else:
            return True

    @discord.ui.button(
        style=discord.ButtonStyle.success, emoji="\N{HEAVY CHECK MARK}\N{VARIATION SELECTOR-16}"
    )
    async def accept_button(self, interaction: discord.Interaction, button: Button):
        fusioner = self.fusion._get_fusioner(interaction.user)
        if fusioner.accepted:
            await interaction.response.send_message(
                "You have already accepted this fusion.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await self.fusion.confirm(fusioner)
        if result:
            await interaction.followup.send("The fusion is done!", ephemeral=True)
        else:
            await interaction.followup.send(
                ":warning: An error occurred while concluding the fusion.", ephemeral=True
            )

    @discord.ui.button(
        style=discord.ButtonStyle.danger,
        emoji="\N{HEAVY MULTIPLICATION X}\N{VARIATION SELECTOR-16}",
    )
    async def deny_button(self, interaction: discord.Interaction, button: Button):
        await self.fusion.user_cancel(self.fusion._get_fusioner(interaction.user))
        await interaction.response.send_message("Fusion has been cancelled.", ephemeral=True)


class FusionMenu:
    def __init__(
        self,
        cog: FusionCog,
        interaction: discord.Interaction,
        fusionerUser: FusingUser,

    ):
        self.cog = cog
        self.bot = cast("BallsDexBot", interaction.client)
        self.channel: discord.TextChannel = interaction.channel
        self.fusionerUser = fusionerUser
        self.embed = discord.Embed()
        self.task: asyncio.Task | None = None
        self.current_view: FusionView | ConfirmView = FusionView(self)
        self.message: discord.Message

    def _get_fusioner(self, user: discord.User | discord.Member) -> FusingUser:
        if user.id == self.fusionerUser.user.id:
            return self.fusionerUser
        raise RuntimeError(f"User with ID {user.id} cannot be found in the fusion")
    
    def _generate_embed(self):
        add_command = self.cog.add.extras.get("mention", "`/fusion add`")
        remove_command = self.cog.remove.extras.get("mention", "`/fusion remove`") 

        self.embed.title = f"{settings.collectible_name.title()}s fusion"
        self.embed.color = discord.Colour.yellow()
        self.embed.description = (
            f"Add or remove {settings.collectible_name}s you want to fuse to a better ball "
            f"using the {add_command} and {remove_command} commands.\n"
            "Once you're finished, click the lock button below to confirm your fusion.\n"
            "You have to use exactly 10 Countryballs to fuse in an better one.\n\n"
            "*You have 10 minutes before this interaction ends.*"
        )
        self.embed.set_footer(
            text="This message is updated every 15 seconds, "
            "but you can keep on editing your proposal."
        )

    def _get_prefix_emote(self, fusioner: FusingUser) -> str:
        if fusioner.cancelled:
            return "\N{NO ENTRY SIGN}"
        elif fusioner.accepted:
            return "\N{WHITE HEAVY CHECK MARK}"
        elif fusioner.locked:
            return "\N{LOCK}"
        else:
            return ""

    def _build_list_of_strings(self, fusioner: FusingUser, short: bool = False) -> list[str]:
        # this builds a list of strings always lower than 1024 characters
        # while not cutting in the middle of a line
        proposal: list[str] = [""]
        i = 0
    
        for countryball in fusioner.proposal:
            cb_text = countryball.description(short=short, include_emoji=True, bot=self.bot)
            if fusioner.locked:
                text = f"- *{cb_text}*\n"
            else:
                text = f"- {cb_text}\n"
            if fusioner.cancelled:
                text = f"~~{text}~~"

            if len(text) + len(proposal[i]) > 1024:
                # move to a new list element
                i += 1
                proposal.append("")
            proposal[i] += text

        if not proposal[0]:
            proposal[0] = "*Empty*"

        return proposal

    def update_proposals(self, compact: bool = False):
        """
        Update the fields in the embed according to their current proposals.

        Parameters
        ----------
        compact: bool
            If `True`, display countryballs in a compact way.
        """
        self.embed.clear_fields()

        # first, build embed strings
        # to play around the limit of 1024 characters per field, we'll be using multiple fields
        # these vars are list of fields, being a list of lines to include
        fusioner_proposal = self._build_list_of_strings(self.fusionerUser, compact)

        # then display the text. first page is easy
        self.embed.add_field(
            name=f"{self._get_prefix_emote(self.fusionerUser)} {self.fusionerUser.user.name}",
            value=fusioner_proposal[0],
            inline=True,
        )

        if len(fusioner_proposal) > 1:
            # we'll have to trick for displaying the other pages
            # fields have to stack themselves vertically
            # to do this, we add a 3rd empty field on each line (since 3 fields per line)
            i = 1
            while i < len(fusioner_proposal):
                self.embed.add_field(name="\u200B", value="\u200B", inline=True)  # empty

                if i < len(fusioner_proposal):
                    self.embed.add_field(name="\u200B", value=fusioner_proposal[i], inline=True)
                else:
                    self.embed.add_field(name="\u200B", value="\u200B", inline=True)

                # always add an empty field at the end, otherwise the alignment is off
                self.embed.add_field(name="\u200B", value="\u200B", inline=True)
                i += 1

        if len(self.embed) > 6000 and not compact:
            self.update_proposals(compact=True)

    async def update_message_loop(self):
        """
        A loop task that updates each 15 second the menu with the new content.
        """

        assert self.task
        start_time = datetime.utcnow()

        while True:
            await asyncio.sleep(15)
            if datetime.utcnow() - start_time > timedelta(minutes=10):
                self.embed.colour = discord.Colour.dark_red()
                await self.cancel("The fusion timed out")
                return

            try:
                self.update_proposals()
                await self.message.edit(embed=self.embed)
            except Exception:
                log.exception(
                    f"Failed to refresh the fusion menu guild={self.message.guild.id} "
                    f"fusioner1={self.fusionerUser.user.id}"
                )
                self.embed.colour = discord.Colour.dark_red()
                await self.cancel("The fusion timed out")
                return 

    async def start(self):
        """
        Start the fusion by sending the initial message and opening up the proposals.
        """
        self._generate_embed()
        self.update_proposals()
        self.message = await self.channel.send(
            content=f"{self.fusionerUser.user.name} started fusioning",
            embed=self.embed,
            view=self.current_view,
        )
        self.task = self.bot.loop.create_task(self.update_message_loop())

    async def cancel(self, reason: str = "The fusion has been cancelled."):
        """
        Cancel the fusion immediately.
        """
        if self.task:
            self.task.cancel()

        for countryball in self.fusionerUser.proposal:
            del self.bot.locked_balls[countryball.id]

        self.current_view.stop()
        for item in self.current_view.children:
            item.disabled = True

        self.update_proposals()
        self.embed.description = f"**{reason}**"
        await self.message.edit(content=None, embed=self.embed, view=self.current_view)

    async def lock(self, fusioner: FusingUser):
        """
        Mark a user's proposal as locked, ready for next stage
        """
        fusioner.locked = True
        
        if self.task:
            self.task.cancel()
        self.current_view.stop()
        self.update_proposals()

        self.embed.colour = discord.Colour.yellow()
        self.embed.description = (
            "You can now confirm to conclude this fusion."
        )
        self.current_view = ConfirmView(self)
        await self.message.edit(content=None, embed=self.embed, view=self.current_view)

    async def user_cancel(self, fusioner: FusingUser):
        """
        Register a user request to cancel the fusion
        """
        fusioner.cancelled = True
        self.embed.colour = discord.Colour.red()
        await self.cancel()

    async def perform_fusion(self):
        fuse_countryballs: list[BallInstance] = []
        

        for countryball in self.fusionerUser.proposal:
            await countryball.refresh_from_db()
            if countryball.player.discord_id != self.fusionerUser.player.discord_id:
                # This is a invalid mutation, the player is not the owner of the countryball
                raise InvalidFusionOperation()
            countryball.player = self.fusionerUser.player
            countryball.fusion_player = self.fusionerUser.player
            countryball.favorite = False
            fuse_countryballs.append(countryball)

        for ball in fuse_countryballs:
            await ball.delete()
        instance = await BallInstance.create(
            ball=fuse_countryballs[0].countryball,
            player=self.fusionerUser.player,
            shiny=(random.randint(1, 4096) == 1),
            attack_bonus=random.randint(-40, 40),
            health_bonus=random.randint(-40, 40),
            special= await Special.get(pk=int(12)),
            )

    async def confirm(self, fusioner: FusingUser) -> bool:
        """
        Mark a user's proposal as accepted. If both user accept, end the fusion now

        If the fusion is concluded, return True, otherwise if an error occurs, return False
        """
        result = True
        fusioner.accepted = True
        self.update_proposals()
        
        if self.task and not self.task.cancelled():
            # shouldn't happen but just in case
            self.task.cancel()

        self.embed.description = "Fusion done!"
        self.embed.colour = discord.Colour.green()
        self.current_view.stop()
        for item in self.current_view.children:
            item.disabled = True
        
        try:
            await self.perform_fusion()
        except InvalidFusionOperation:
            log.warning(f"Illegal fusion operation from {self.fusionerUser=}")
            self.embed.description = (
                f":warning: An attempt to modify the {settings.collectible_name}s "
                "during the fusion was detected and the fusion was cancelled."
            )
            self.embed.colour = discord.Colour.red()
            result = False
        except Exception:
            log.exception(f"Failed to conclude fusion {self.fusionerUser=}")
            self.embed.description = "An error occured when concluding the fusion."
            self.embed.colour = discord.Colour.red()
            result = False

        await self.message.edit(content=None, embed=self.embed, view=self.current_view)
        return result
