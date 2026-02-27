"""カードデータに関する共通ユーティリティ。"""

_EFFECT_LABELS = {
    "draw": lambda n: f"+{n} カードを引く",
    "action": lambda n: f"+{n} アクション",
    "buy": lambda n: f"+{n} 購入",
    "coin": lambda n: f"+{n} コイン",
    "coin_value": lambda n: f"+{n} コイン",
    "victory_points": lambda n: f"{n} 勝利点",
    "attack_discard_to": lambda n: f"【攻撃】他者は手札{n}枚まで捨てる",
    "discard_draw": lambda _: "好きな枚数を捨て、同数引く",
    "gain_card_up_to": lambda n: f"コスト{n}以下を獲得",
    "trash": lambda n: f"手札{n}枚まで廃棄",
    "trash_and_gain": lambda n: f"1枚廃棄→コスト+{n}以下を獲得",
    "trash_treasure_gain_treasure": lambda n: f"財宝廃棄→コスト+{n}以下の財宝を手札に",
    "trash_copper_for_coin": lambda n: f"最安財宝を廃棄で+{n}コイン",
    "opponents_draw": lambda n: f"他者: +{n} ドロー",
    "gain_card_to_hand": lambda n: f"コスト{n}以下を手札に獲得, 手札1枚をデッキトップに",
    "topdeck_from_discard": lambda _: "捨て札1枚をデッキトップに",
    "discard_top_play_action": lambda _: "デッキトップ1枚を捨て札に。アクションならプレイ可",
    "gain_treasure_topdeck_attack_victory": lambda n: f"コスト{n}の財宝をデッキトップに獲得,【攻撃】他者は勝利点をデッキトップに",
    "reveal_trash_discard_topdeck": lambda n: f"デッキトップ{n}枚を公開し、各々廃棄/捨て/戻す",
}


def build_effect_text(card: dict) -> str:
    """effects 配列からカード効果の要約テキストを生成する。"""
    effects = card.get("effects", [])
    if not effects:
        if card.get("type") == "treasure" and card.get("coin_value") is not None:
            effects = [{"type": "coin_value", "amount": card["coin_value"]}]
        elif card.get("type") == "victory" and card.get("victory_points") is not None:
            effects = [{"type": "victory_points", "amount": card["victory_points"]}]
    parts = []
    for ef in effects:
        fn = _EFFECT_LABELS.get(ef.get("type"))
        if fn:
            parts.append(fn(ef.get("amount", 0)))
    if card.get("reaction") == "block_attack":
        parts.append("攻撃を無効化")
    return ", ".join(parts)
