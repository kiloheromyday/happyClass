from backend.app.repositories.classroom import one
from backend.app.repositories.database import connect

DEFAULT_PROFILE = {'nickname': '', 'bio': '', 'interests': '', 'avatar_color': 'sage', 'major': '', 'grade': '', 'study_goal': '', 'learning_style': ''}


def get_profile(user_id):
    with connect() as connection:
        profile = one(connection.execute('SELECT nickname,bio,interests,avatar_color,major,grade,study_goal,learning_style FROM user_profiles WHERE user_id=?', (user_id,))) or DEFAULT_PROFILE.copy()
        avatar = connection.execute('SELECT digest FROM user_avatars WHERE user_id=?', (user_id,)).fetchone()
        return {**profile, 'avatar_url': f'/api/avatars/{user_id}/{avatar[0]}' if avatar else None}


def save_profile(connection, user_id, payload):
    connection.execute('UPDATE users SET email=? WHERE id=?', (payload.email, user_id))
    connection.execute('''INSERT INTO user_profiles(user_id,nickname,bio,interests,avatar_color,major,grade,study_goal,learning_style) VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET nickname=excluded.nickname,bio=excluded.bio,
        interests=excluded.interests,avatar_color=excluded.avatar_color,major=excluded.major,
        grade=excluded.grade,study_goal=excluded.study_goal,learning_style=excluded.learning_style''',
        (user_id, payload.nickname, payload.bio, payload.interests, payload.avatar_color, payload.major, payload.grade, payload.study_goal, payload.learning_style))
