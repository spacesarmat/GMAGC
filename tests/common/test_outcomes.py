from gmagc_common import protocol
from gmagc_desktop.service.results import Outcome


def test_outcome_constants_match_the_server_enum():
    assert {outcome.value for outcome in Outcome} == {
        protocol.OUTCOME_FOUND,
        protocol.OUTCOME_LOW_CONFIDENCE,
        protocol.OUTCOME_NO_PROJECTION,
    }
