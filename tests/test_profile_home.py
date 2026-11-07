import io

import pytest
from PIL import Image

from backend.app.repositories.database import connect, initialize_database
from test_classroom import HEADERS, actors, classroom_for, schedule, submit

URL = '/api/users/me/avatar'


def picture(format='PNG', size=(640, 480), color='#88aa66', **options):
    out = io.BytesIO()
    Image.new('RGB', size, color).save(out, format=format, **options)
    return out.getvalue()


def upload(actors, actor='student', data=None, media='image/png', **params):
    return actors[actor]['client'].put(URL, content=picture() if data is None else data, headers={**HEADERS, 'Content-Type': media}, params=params)


@pytest.mark.parametrize('format,media', [('JPEG', 'image/jpeg'), ('PNG', 'image/png'), ('WEBP', 'image/webp')])
def test_avatar_roundtrip_crop_persistence_and_public_cards(actors, format, media):
    response = upload(actors, data=picture(format), media=media, zoom=2, x=0, y=1)
    assert response.status_code == 200, response.text
    url = response.json()['data']['avatar_url']
    client = actors['student']['client']
    image = client.get(url)
    assert image.status_code == 200 and image.headers['content-type'] == 'image/jpeg'
    assert image.headers['cache-control'] == 'private, no-store'
    with Image.open(io.BytesIO(image.content)) as decoded:
        assert decoded.size == (256, 256) and not decoded.getexif() and not decoded.info.get('icc_profile')
    initialize_database()
    assert client.get('/api/users/me').json()['data']['avatar_url'] == url
    peer = actors['other_student']['client']
    assert peer.get(url).status_code == 200
    cards = peer.get('/api/buddies/search', params={'username': 'student'}).json()['data']['items']
    assert cards[0]['avatar_url'] == url and 'email' not in cards[0]
    assert actors['teacher']['client'].get(url).status_code == 404
    assert actors['admin']['client'].get(url).status_code == 200


def test_avatar_position_is_applied_and_metadata_removed(actors):
    source = Image.new('RGB', (200, 100), 'red')
    source.paste('blue', (100, 0, 200, 100))
    exif = Image.Exif(); exif[270] = 'private original metadata'
    output = io.BytesIO(); source.save(output, format='JPEG', exif=exif)
    url = upload(actors, data=output.getvalue(), media='image/jpeg', x=1).json()['data']['avatar_url']
    result = actors['student']['client'].get(url)
    with Image.open(io.BytesIO(result.content)) as decoded:
        red, green, blue = decoded.getpixel((128, 128))
        assert blue > 200 and red < 50 and len(decoded.getexif()) == 0
    assert b'private original metadata' not in result.content


def test_avatar_exif_orientation_and_upload_rate(actors):
    source = Image.new('RGB', (200, 100), 'red'); source.paste('blue', (100, 0, 200, 100))
    exif = Image.Exif(); exif[274] = 6
    out = io.BytesIO(); source.save(out, format='JPEG', exif=exif)
    response = upload(actors, data=out.getvalue(), media='image/jpeg', y=0)
    with Image.open(io.BytesIO(actors['student']['client'].get(response.json()['data']['avatar_url']).content)) as decoded:
        red, green, blue = decoded.getpixel((128, 128))
        assert red > 200 and blue < 50
    for _ in range(29):
        assert upload(actors, data=b'bad').status_code == 422
    assert upload(actors).status_code == 429


def test_avatar_replacement_delete_and_owner_isolation(actors):
    first = upload(actors).json()['data']['avatar_url']
    second = upload(actors, data=picture(size=(100, 100), color='blue')).json()['data']['avatar_url']
    assert first != second and actors['student']['client'].get(first).status_code == 404
    assert actors['other_student']['client'].delete(URL, headers=HEADERS).status_code == 200
    assert actors['student']['client'].get(second).status_code == 200
    assert actors['student']['client'].delete(URL, headers=HEADERS).json()['data']['avatar_url'] is None
    assert actors['student']['client'].get(second).status_code == 404
    assert actors['student']['client'].delete(URL, headers=HEADERS).status_code == 200
    staff_url = upload(actors, actor='teacher').json()['data']['avatar_url']
    assert actors['student']['client'].get(staff_url).status_code == 404
    with connect() as connection:
        connection.execute("UPDATE users SET status='DISABLED' WHERE id=?", (actors['teacher']['user']['id'],))
    assert actors['admin']['client'].get(staff_url).status_code == 404


@pytest.mark.parametrize('data,media,status', [(b'<svg/>', 'image/svg+xml', 415), (b'not an image', 'image/png', 422), (b'', 'image/png', 413), (b'x' * (2 * 1024 * 1024 + 1), 'image/png', 413)])
def test_avatar_rejects_invalid_and_oversized_uploads(actors, data, media, status):
    assert upload(actors, data=data, media=media).status_code == status


def test_avatar_rejects_mismatched_animated_small_large_and_truncated_images(actors):
    assert upload(actors, data=picture('JPEG'), media='image/png').status_code == 415
    assert upload(actors, data=picture(size=(16, 16))).status_code == 422
    assert upload(actors, data=picture(size=(4097, 32))).status_code == 422
    assert upload(actors, data=picture()[:50]).status_code == 422
    out = io.BytesIO()
    Image.new('RGB', (64, 64), 'red').save(out, format='PNG', save_all=True, append_images=[Image.new('RGB', (64, 64), 'blue')], duration=100, loop=0)
    assert upload(actors, data=out.getvalue()).status_code == 422


@pytest.mark.parametrize('params', [{'zoom': 0}, {'zoom': 'nan'}, {'zoom': 4}, {'x': -1}, {'y': 2}])
def test_avatar_rejects_invalid_crop(actors, params):
    assert upload(actors, **params).status_code == 422


def test_avatar_requires_login_and_origin(client, actors):
    assert client.put(URL, content=picture(), headers={**HEADERS, 'Content-Type': 'image/png'}).status_code == 401
    student = actors['student']['client']
    assert student.put(URL, content=picture(), headers={'Content-Type': 'image/png'}).status_code == 403
    assert student.delete(URL).status_code == 403
    assert client.get('/api/users/me/overview').status_code == 401


def test_profile_overview_uses_own_data_and_role(actors):
    mine = classroom_for(actors)
    other = classroom_for(actors, owner='other_teacher')
    schedule(actors, mine); schedule(actors, other, ('other_student',))
    submit(actors['student'], mine); submit(actors['other_student'], other)
    with connect() as connection:
        connection.execute("INSERT INTO personal_notes(user_id,title,content,created_at,updated_at) VALUES (?,'私有','正文','2026-11-03T00:00:00Z','2026-11-03T00:00:00Z')", (actors['student']['user']['id'],))
    data = actors['student']['client'].get('/api/users/me/overview').json()['data']
    assert [item['value'] for item in data['metrics']] == [1, 1, 1, 0]
    assert data['pending_notes'] == 1
    staff = actors['teacher']['client'].get('/api/users/me/overview').json()['data']
    assert [item['value'] for item in staff['metrics']] == [1, 1, 1]
    assert staff['pending_notes'] is None
