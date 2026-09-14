import pytest
import responses

from oper_monitor.discovery import PROGRAMME_URL, DiscoveryError, ProgrammeParser, discover_events


def performance(event_id=123, date='2099-10-03T18:00:00'):
    return f'''<div class="performance"><meta itemprop="startDate" content="{date}">
    <h2><span>Lucia &amp; friends</span></h2>
    <a href="https://ticket.staatstheater-stuttgart.de/eventim.webshop/webticket/shop?event={event_id}&amp;language=de">Restkarten</a></div>'''


def test_extracts_id_title_date_and_deduplicates():
    parser = ProgrammeParser()
    parser.feed(performance() * 2 + performance(456, '2000-01-01T18:00:00'))
    assert len(parser.events) == 1
    event = parser.events[123]
    assert event.key == 'event-123'
    assert event.url.endswith('eventId=123')
    assert event.label == 'Lucia & friends — 2099-10-03T18:00:00'


@responses.activate
def test_discovers_every_month_and_deduplicates():
    responses.get(PROGRAMME_URL, body=performance() + '<a href="/spielplan/kalender/2099-11/">Nov</a>')
    responses.get(PROGRAMME_URL + 'kalender/2099-11/', body=performance() + performance(456))
    assert [event.event_id for event in discover_events()] == [123, 456]
    assert len(responses.calls) == 2


@responses.activate
def test_missing_month_fails_instead_of_returning_partial_list():
    responses.get(PROGRAMME_URL, body=performance() + '<a href="/spielplan/kalender/2099-11/">Nov</a>')
    responses.get(PROGRAMME_URL + 'kalender/2099-11/', body='<html>Unavailable</html>')
    with pytest.raises(DiscoveryError, match='No programme entries'):
        discover_events()


@responses.activate
def test_empty_discovery_is_an_error():
    responses.get(PROGRAMME_URL, body='<html>Unavailable</html>')
    with pytest.raises(DiscoveryError):
        discover_events()
