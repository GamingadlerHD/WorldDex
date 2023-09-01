from typing import TYPE_CHECKING

from ballsdex.packages.gafusionv2.cog import Fusion

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot


async def setup(bot: "BallsDexBot"):
    await bot.add_cog(Fusion(bot))
