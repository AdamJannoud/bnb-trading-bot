"""Server-side wallet tools. Run these on the host; nothing here is reachable from Telegram.

    python wallet_tools.py export --user-id 123456789 [--chain EVM]

The key is written to the terminal that ran the command and nowhere else.
"""
import argparse
import sys


def export_private_key(user_id: int, chain_type: str = "EVM", out=None) -> int:
    out = out or sys.stdout
    if not out.isatty():
        print("Refusing to export: output is not an interactive terminal. "
              "Run this directly in a terminal so the key is not written to a file or log.", file=sys.stderr)
        return 2

    from wallet_manager import get_decrypted_private_key

    pk = get_decrypted_private_key(user_id, chain_type=chain_type)
    if pk is None:
        print(f"No {chain_type} wallet stored for user {user_id}.", file=sys.stderr)
        return 1

    out.write(f"{chain_type} private key for user {user_id} (do not paste into chat):\n{pk}\n")
    out.flush()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Owner-only wallet tools, run on the server.")
    sub = parser.add_subparsers(dest="command", required=True)
    exp = sub.add_parser("export", help="Print a user's private key to this terminal.")
    exp.add_argument("--user-id", type=int, required=True)
    exp.add_argument("--chain", default="EVM", choices=["EVM", "SOLANA"])
    args = parser.parse_args(argv)

    if args.command == "export":
        return export_private_key(args.user_id, args.chain)
    return 1


if __name__ == "__main__":
    sys.exit(main())
