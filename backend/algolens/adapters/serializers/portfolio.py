"""Portfolio HTTP serializers."""


def serialize_strategy_detail(strategy):
    return strategy


def serialize_strategy_list(strategies):
    return {"strategies": strategies}
