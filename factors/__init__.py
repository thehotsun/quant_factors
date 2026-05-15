from factors.base import BaseFactor
from factors.meat import PorkFactor
from factors.feed import SoybeanMealFactor, CornFactor, SoybeanFactor, RapeseedMealFactor
from factors.cross import (
    PigGrainRatio, FeedCostIndex, CrushMargin,
    PigChickenSpread, EggFeedRatio,
    CopperGoldRatio, OilGoldLink, ForexCommodityLink, PMIMetalsLink,
    IronRebarCostLink,
)
from factors.macro import (
    CPIFactor, PMIFactor, ForexFactor, MoneySupplyFactor,
    CpiGoldFactor, CbotSoybeanFactor, SocialFinancingFactor, VixFactor,
)
from factors.energy import CrudeOilFactor, NaturalGasFactor, OilGasRatio, OilAssetsFactor
from factors.metals import CopperFactor, AluminumFactor, RebarFactor, GoldFactor, SilverFactor, IronOreFactor
from factors.technical import MomentumFactor, VolatilityFactor, TermStructureFactor, SeasonalityFactor