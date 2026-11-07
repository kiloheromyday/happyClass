"""Create privileged accounts locally; passwords are read without echoing."""
import argparse
import getpass

from pydantic import ValidationError

from backend.app.errors import AppError
from backend.app.models.auth import RegisterRequest
from backend.app.repositories.database import initialize_database
from backend.app.services.auth import provision_user


def main():
    parser = argparse.ArgumentParser(description="在本机创建课堂情绪检查器账号")
    parser.add_argument("command", choices=["create-user"])
    parser.add_argument("--username", required=True)
    parser.add_argument("--role", required=True, choices=["STUDENT", "TEACHER", "ADMIN"])
    parser.add_argument("--email")
    args = parser.parse_args()
    password = getpass.getpass("密码（至少10位，包含字母和数字）: ")
    if password != getpass.getpass("再次输入密码: "):
        parser.exit(1, "两次密码不一致，未创建账号。\n")
    try:
        payload = RegisterRequest(username=args.username, password=password, email=args.email)
        initialize_database()
        user = provision_user(payload.username, payload.password, args.role, payload.email)
    except ValidationError:
        parser.exit(1, "账号格式或密码强度不符合要求，未创建账号。\n")
    except AppError as error:
        parser.exit(1, error.message + "\n")
    print(f"已创建 {user['role']} 账号：{user['username']}。请在网页登录。")


if __name__ == "__main__":
    main()
