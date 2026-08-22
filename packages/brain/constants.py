"""Channel economics + LTV constants (Brain-side view of data/calibration_sources.md).

These are coarse, literature-level priors used by the EV policy — deliberately
NOT simulator internals (Rules §17.6/§17.7). Sources cited in
data/calibration_sources.md §5–6.
"""

from reflex.core.enums import Channel, LtvBand

# Direct channel cost per dispatched action, paise.
CHANNEL_COST_PAISE: dict[Channel | None, int] = {
    Channel.WA_SIM: 80,
    Channel.SMS_SIM: 18,
    Channel.EMAIL_SIM: 2,
    Channel.VOICE_SIM: 400,
    Channel.RAZORPAY_TM: 0,
    Channel.NONE: 0,
    None: 0,
}

# Margin proxy per customer LTV band (annoyance denominator), paise.
LTV_BAND_VALUE_PAISE: dict[LtvBand, int] = {
    LtvBand.LOW: 200_000,
    LtvBand.MID: 600_000,
    LtvBand.HIGH: 1_500_000,
}
