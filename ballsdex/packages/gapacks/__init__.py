from typing import TYPE_CHECKING

from ballsdex.packages.gapacks.cog import gaPacks #Import Class
from ballsdex.packages.gapacks.cog import gaPlayers

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot


async def setup(bot: "BallsDexBot"):
    await bot.add_cog(gaPacks(bot))
    await bot.add_cog(gaPlayers(bot))