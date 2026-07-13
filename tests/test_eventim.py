import pytest

from oper_monitor.eventim import EventimError, decode_availability, decode_block_infos, decode_mapping, decode_seatmap


def test_decodes_delta_encoded_mapping() -> None:
    mappings, categories = decode_mapping(
        {
            "priceCategories": [
                {"id": 1, "name": "Preisgruppe 1", "color": "#111111"},
                {"id": 2, "name": "Preisgruppe 2", "color": "#222222"},
            ],
            "seats": [[1, 0, 2], [1, 0, 0], [3, 1, -1]],
        }
    )
    assert list(mappings) == [1, 2, 5]
    assert mappings[1].price_category_id == 2
    assert mappings[2].price_category_id == 2
    assert mappings[5].status == 1
    assert mappings[5].price_category_id == 1
    assert categories[2].name == "Preisgruppe 2"


def test_decodes_only_availability_status_one() -> None:
    snapshot = decode_availability(
        {
            "seatmapId": "hall-1",
            "seatmapVersion": 12,
            "timestamp": 1234,
            "seats": [[1, 1], [1, 2], [3, 1], [1, 0]],
        }
    )
    assert snapshot.available_seat_ids == frozenset({1, 5})


def test_decodes_seatmap_block_order_and_metadata() -> None:
    definition = decode_seatmap(
        {
            "seatmapId": "hall-1",
            "seatmapVersion": 12,
            "areas": [{"blocks": [{"id": 5}, {"id": 6}]}, {"blocks": [{"id": 5}]}],
        }
    )
    assert definition.block_ids == (5, 6)
    seats = decode_block_infos(
        [
            {
                "id": 5,
                "name": "Parkett links",
                "seatInfos": [
                    {"id": 1, "row": "1", "seatNumber": "29", "GA": False, "handicap": 0},
                    {"id": 2, "row": "1", "seatNumber": "27", "GA": False, "handicap": 0},
                ],
            }
        ]
    )
    assert [seat.seat_number for seat in seats] == ["29", "27"]


def test_rejects_malformed_payload() -> None:
    with pytest.raises(EventimError):
        decode_availability({"seats": []})
