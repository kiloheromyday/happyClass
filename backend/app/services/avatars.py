import hashlib
import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from backend.app.errors import AppError
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories.classroom import audit
from backend.app.repositories.database import connect

MAX_BYTES = 2 * 1024 * 1024
TYPES = {'image/jpeg': 'JPEG', 'image/png': 'PNG', 'image/webp': 'WEBP'}


def normalize(data, media_type, zoom, x, y):
    if media_type not in TYPES:
        raise AppError(415, 'AVATAR_TYPE', '请选择 JPG、PNG 或 WebP 静态图片')
    if not data or len(data) > MAX_BYTES:
        raise AppError(413, 'AVATAR_SIZE', '头像图片应在 2 MB 以内，且不能为空')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.format != TYPES[media_type]:
                    raise AppError(415, 'AVATAR_TYPE', '图片内容与格式不一致，请重新选择图片')
                if getattr(source, 'n_frames', 1) != 1:
                    raise AppError(422, 'AVATAR_ANIMATED', '请选择静态图片，暂不支持动图')
                if min(source.size) < 32 or max(source.size) > 4096:
                    raise AppError(422, 'AVATAR_DIMENSIONS', '图片宽高需在 32～4096 像素之间')
                source.load()
                oriented = ImageOps.exif_transpose(source).convert('RGBA')
                width, height = oriented.size
                side = min(width, height) / zoom
                left, top = (width - side) * x, (height - side) * y
                cropped = oriented.crop((round(left), round(top), round(left + side), round(top + side))).resize((256, 256), Image.Resampling.LANCZOS)
                rgb = Image.new('RGB', (256, 256), '#fffefa')
                rgb.paste(cropped, mask=cropped.getchannel('A'))
                output = io.BytesIO()
                rgb.save(output, format='JPEG', quality=88, optimize=True)
                return output.getvalue()
    except AppError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise AppError(422, 'AVATAR_INVALID', '图片无法读取，请更换一张完整的图片') from error


def save(user, image):
    digest = hashlib.sha256(image).hexdigest()
    with connect() as connection:
        connection.execute('''INSERT INTO user_avatars(user_id,image,digest,updated_at) VALUES (?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET image=excluded.image,digest=excluded.digest,updated_at=excluded.updated_at''', (user['id'], image, digest, utc_text(now_utc())))
        audit(connection, user['id'], 'AVATAR_UPDATED', {})


def remove(user):
    with connect() as connection:
        connection.execute('DELETE FROM user_avatars WHERE user_id=?', (user['id'],))
        audit(connection, user['id'], 'AVATAR_REMOVED', {})


def image_for(user_id, digest, viewer):
    with connect() as connection:
        row = connection.execute('''SELECT a.image,u.role FROM user_avatars a JOIN users u ON u.id=a.user_id
            WHERE a.user_id=? AND a.digest=? AND u.status='ACTIVE' ''', (user_id, digest)).fetchone()
    if not row or not (viewer['id'] == user_id or viewer['role'] == 'ADMIN' or viewer['role'] == row[1] == 'STUDENT'):
        raise AppError(404, 'AVATAR_NOT_FOUND', '头像不存在')
    return row[0]
