import discord

from discord import app_commands
from discord.ext import commands

from typing import TYPE_CHECKING
from collections import defaultdict

from ballsdex.settings import settings
from ballsdex.core.models import Player
from ballsdex.core.utils.transformers import BallInstanceTransform
from ballsdex.core.utils.buttons import ConfirmChoiceView
from ballsdex.packages.gafusionv2.menu import FusionMenu, FusingUser

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot


class Fusion(commands.GroupCog):
    """
    Fuse 10 of your dupes to an better Countryball.
    """

    def __init__(self, bot: "BallsDexBot"):
        self.bot = bot
        self.fusion: dict[int, dict[int, list[FusionMenu]]] = defaultdict(lambda: defaultdict(list))

    def get_fusion(
        self,
        interaction: discord.Interaction | None = None,
        *,
        channel: discord.TextChannel | None = None,
        user: discord.User | discord.Member | None = None,
    ) -> tuple[FusionMenu, FusingUser] | tuple[None, None]:
        """
        Find an ongoing fusion for the given interaction.

        Parameters
        ----------
        interaction: discord.Interaction
            The current interaction, used for getting the guild, channel and author.

        Returns
        -------
        tuple[FusionMenu, FusingUser] | tuple[None, None]
            A tuple with the `FusionMenu` and `FusingUser` if found, else `None`.
        """
        guild: discord.Guild
        if interaction:
            guild = interaction.guild
            channel = interaction.channel
            user = interaction.user
        else:
            guild = channel.guild

        if guild.id not in self.fusion:
            return (None, None)
        if channel.id not in self.fusion[guild.id]:
            return (None, None)
        to_remove: list[FusionMenu] = []
        for fuse in self.fusion[guild.id][channel.id]:
            if (
                fuse.current_view.is_finished()
                or fuse.fusionerUser.cancelled
            ):
                # remove what was supposed to have been removed
                to_remove.append(fuse)
                continue
            try:
                fusioner = fuse._get_fusioner(user)
            except RuntimeError:
                continue
            else:
                break
        else:
            for fuse in to_remove:
                self.fusion[guild.id][channel.id].remove(fuse)
            return (None, None)

        for fuse in to_remove:
            self.fusion[guild.id][channel.id].remove(fuse)
        return (fuse, fusioner)
    # do not remove credits here
    @app_commands.command()
    async def begin(self, interaction: discord.Interaction,):
        """
        Begin fusing. - Made by GamingadlerHD
        """

        fusion, fusionerUser = self.get_fusion(interaction)
        if fusion or fusionerUser:
            await interaction.response.send_message(
                "You already have an ongoing fusion.", ephemeral=True
            )
            return

        player, _ = await Player.get_or_create(discord_id=interaction.user.id)
        menu = FusionMenu(
            self, interaction, FusingUser(interaction.user, player),
        )
        self.fusion[interaction.guild.id][interaction.channel.id].append(menu)
        await menu.start()
        await interaction.response.send_message("Fusion started!", ephemeral=True)
    # do not remove credits here
    @app_commands.command()
    async def add(self, interaction: discord.Interaction, countryball: BallInstanceTransform):
        """
        Add a countryball to the ongoing fusion.  - Made by GamingadlerHD

        Parameters
        ----------
        countryball: BallInstance
            The countryball you want to add to your proposal
        """
        if not countryball:
            return
        if not countryball.countryball.tradeable:
            await interaction.response.send_message(
                "You cannot fuse this countryball.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        if countryball.favorite:
            view = ConfirmChoiceView(interaction)
            await interaction.followup.send(
                "This countryball is a favorite, are you sure you want to fuse it?",
                view=view,
                ephemeral=True,
            )
            await view.wait()
            if not view.value:
                return

        fusion, fusioner = self.get_fusion(interaction)
        if not fusion or not fusioner:
            await interaction.followup.send("You do not have an ongoing fusion.", ephemeral=True)
            return
        if fusioner.locked:
            await interaction.followup.send(
                "You have locked your proposal, it cannot be edited! "
                "You can click the cancel button to stop the fusion instead.",
                ephemeral=True,
            )
            return
        if countryball in fusioner.proposal:
            await interaction.followup.send(
                f"You already have this {settings.collectible_name} in your proposal.",
                ephemeral=True,
            )
            return
        if countryball.id in self.bot.locked_balls:
            await interaction.followup.send(
                "This countryball is currently in an active fusion or donation, "
                "please try again later.",
                ephemeral=True,
            )
            return

        self.bot.locked_balls[countryball.id] = None
        fusioner.proposal.append(countryball)
        await interaction.followup.send(
            f"{countryball.countryball.country} added.", ephemeral=True
        )
    # do not remove credits here
    @app_commands.command()
    async def remove(self, interaction: discord.Interaction, countryball: BallInstanceTransform):
        """
        Remove a countryball from what you proposed in the ongoing fusion.  - Made by GamingadlerHD

        Parameters
        ----------
        countryball: BallInstance
            The countryball you want to remove from your proposal
        """
        if not countryball:
            return

        fuse, fusioner = self.get_fusion(interaction)
        if not fuse or not fusioner:
            await interaction.response.send_message(
                "You do not have an ongoing fusion.", ephemeral=True
            )
            return
        if fusioner.locked:
            await interaction.response.send_message(
                "You have locked your proposal, it cannot be edited! "
                "You can click the cancel button to stop the fusion instead.",
                ephemeral=True,
            )
            return
        if countryball not in fusioner.proposal:
            await interaction.response.send_message(
                f"That {settings.collectible_name} is not in your proposal.", ephemeral=True
            )
            return
        fusioner.proposal.remove(countryball)
        await interaction.response.send_message(
            f"{countryball.countryball.country} removed.", ephemeral=True
        )
        del self.bot.locked_balls[countryball.id]
