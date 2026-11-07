from backend.app.repositories.classroom import one, rows


def message(connection, owner_id, message_id):
    return one(connection.execute('SELECT * FROM buddy_wall_messages WHERE owner_id=? AND id=?', (owner_id, message_id)))


def listing(connection, owner_id, user_id, mine, limit, offset):
    where, values = 'm.owner_id=?', [owner_id]
    if mine:
        where += ' AND m.author_id=?'
        values.append(user_id)
    joined = " FROM buddy_wall_messages m JOIN users u ON u.id=m.author_id WHERE u.status='ACTIVE' AND u.role='STUDENT' AND " + where
    count = connection.execute('SELECT count(*)' + joined, values).fetchone()[0]
    items = rows(connection.execute('SELECT m.*' + joined + ' ORDER BY m.created_at DESC,m.id DESC LIMIT ? OFFSET ?', [*values, limit, offset]))
    return items, count


def previous(connection, user_id, request_id):
    return one(connection.execute('SELECT message_id,payload_hash FROM buddy_wall_keys WHERE author_id=? AND request_id=?', (user_id, request_id)))


def add(connection, owner_id, user_id, payload, digest, timestamp):
    identifier = connection.execute('''INSERT INTO buddy_wall_messages(owner_id,author_id,content,visibility,created_at,updated_at)
        VALUES (?,?,?,?,?,?)''', (owner_id, user_id, payload.content, payload.visibility, timestamp, timestamp)).lastrowid
    connection.execute('INSERT INTO buddy_wall_keys(author_id,request_id,message_id,payload_hash,created_at) VALUES (?,?,?,?,?)', (user_id, str(payload.request_id), identifier, digest, timestamp))
    return message(connection, owner_id, identifier)


def sent(connection, user_id, limit, offset):
    total = connection.execute('SELECT count(*) FROM buddy_wall_messages WHERE author_id=?', (user_id,)).fetchone()[0]
    items = rows(connection.execute('''SELECT m.*,u.username AS owner_username,coalesce(p.nickname,'') AS owner_nickname
        FROM buddy_wall_messages m JOIN users u ON u.id=m.owner_id LEFT JOIN user_profiles p ON p.user_id=u.id
        WHERE m.author_id=? ORDER BY m.created_at DESC,m.id DESC LIMIT ? OFFSET ?''', (user_id, limit, offset)))
    return items, total
