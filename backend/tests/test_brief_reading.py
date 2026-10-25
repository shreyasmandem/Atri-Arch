"""The chat reads what the client wrote - typos, counts, floors - and answers in their language."""

from aip.agents.brief_agent import apply_defaults, parse, reply_language, to_request
from aip.api.schemas import SimpleBriefRequest
from aip.domain.plan import RoomType

PROMPT = (
    "i want a 60x40 site building with g+2, and 4 bedrooms, 5 bathrooms, a laundry room,a study room, "
    "an open tuility next to the kitchen, a garage in the ground floor, 2 kitchens, one in groun dand one "
    "in second, i need a gardern (in home, open space)\n\nsouthwest facing road, dedicated puja room"
)


def test_every_room_asked_for_is_read_onto_its_floor():
    b = parse(PROMPT)
    assert (b["levels"], b["bedrooms"], b["bathrooms"], b["road_direction"]) == (3, 4, 5, "SW")
    rooms = b["rooms"]
    assert {"type": "kitchen", "level": 0} in rooms and {"type": "kitchen", "level": 2} in rooms
    assert {"type": "utility", "attach_to": "kitchen"} in rooms
    assert {"type": "garage", "level": 0} in rooms
    assert any(r["type"] == "courtyard" for r in rooms)
    assert {"pooja", "study"} <= set(b["amenities"])


def test_a_second_kitchen_is_added_not_moved():
    reqs = SimpleBriefRequest(**to_request(apply_defaults(parse(PROMPT)))).to_brief().requirements
    kitchens = sorted((r.level, r.count) for r in reqs if r.type is RoomType.KITCHEN)
    assert kitchens == [(0, 1), (2, 1)]
    assert sum(r.count for r in reqs if r.type is RoomType.GARAGE) == 1
    assert sum(r.count for r in reqs if r.type is RoomType.COURTYARD) == 1


def test_counts_spread_over_floors():
    rooms = parse("3 balconies, one on the first and two on the second floor")["rooms"]
    assert {"type": "balcony", "level": 1} in rooms and {"type": "balcony", "level": 2, "count": 2} in rooms


def test_reply_language_follows_the_message_not_a_place_name():
    assert reply_language("a 3bhk in Bengaluru, south facing") == "English"
    assert reply_language("G+1 (2 floors)") == "English"
    assert reply_language("mujhe 3 bedroom ka ghar chahiye").startswith("Hinglish")
    assert reply_language("कितने बेडरूम चाहिए").startswith("Hindi")
