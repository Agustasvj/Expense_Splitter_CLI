import os
import json
from datetime import datetime
from colorama import Fore, Style, init

init(autoreset=True)

# ==================== UI ====================

def banner():
    print(Fore.CYAN + Style.BRIGHT + "\n" + "=" * 60)
    print("💰  EXPENSE SPLITTER  💰".center(60))
    print("=" * 60 + Style.RESET_ALL)

def info(msg):  print(Fore.YELLOW + msg)
def ok(msg):    print(Fore.GREEN + msg)
def err(msg):   print(Fore.RED + "❌ " + msg)
def sec(title): print(Fore.BLUE + f"\n--- {title} ---")


# ==================== FILE I/O ====================

def list_groups():
    return sorted([f for f in os.listdir() if f.endswith(".json")])

def load_data(file_name):
    with open(file_name, "r", encoding="utf-8") as f:
        data = json.load(f)
    normalize_expenses(data)      # migrate old entries to {"payer": ...}
    update_summary(data)          # compute summary/balances in memory
    return data

def save_data(file_name, data):
    # Ensure normalized + updated before saving
    normalize_expenses(data)
    update_summary(data)
    ordered = {
        "summary": data.get("summary", {}),
        "participants": data.get("participants", []),
        "expenses": data.get("expenses", []),
        "balances": data.get("balances", {})
    }
    with open(file_name, "w", encoding="utf-8") as f:
        json.dump(ordered, f, indent=4, ensure_ascii=False)


# ==================== NORMALIZATION ====================

def normalize_expenses(data):
    """Convert any legacy entries {'name': ...} to {'payer': ...} and coerce types."""
    expenses = data.get("expenses", [])
    for e in expenses:
        if "payer" not in e and "name" in e:
            e["payer"] = e.pop("name")
        # coerce amount to float if it was saved as string/int
        try:
            e["amount"] = float(e.get("amount", 0))
        except (TypeError, ValueError):
            e["amount"] = 0.0
        # ensure optional keys exist
        e.setdefault("description", "")
        e.setdefault("time", "")


# ==================== CORE LOGIC ====================

def update_summary(data):
    """
    Compute balances and human summary.

    Rules:
      - If exactly 2 participants: every expense is treated as fully paid *for the other person*.
        So if Garuda pays 250, Agusta owes Garuda 250 (no splitting).
      - If >2 participants: treat each expense as for 'everyone except the payer' equally.
        Each non-payer owes (amount / (n-1)) to the payer.
    """
    participants = data.get("participants", [])
    expenses = data.get("expenses", [])
    n = len(participants)

    # Net balance per person: positive => is owed; negative => owes
    net = {p: 0.0 for p in participants}

    if n == 0:
        data["balances"] = net
        data["summary"] = {"info": "No participants"}
        return

    if n == 1:
        data["balances"] = net
        data["summary"] = {"info": "Only one participant; nothing to settle"}
        return

    if n == 2:
        # Your 2-person rule: all of 'amount' is owed by the other person.
        p1, p2 = participants[0], participants[1]
        for e in expenses:
            payer = e.get("payer")
            amt = float(e.get("amount", 0) or 0)
            if payer == p1:
                # p2 owes p1 the full amount
                net[p1] += amt
                net[p2] -= amt
            elif payer == p2:
                # p1 owes p2 the full amount
                net[p2] += amt
                net[p1] -= amt
            # else ignore malformed payer

        diff = net[p1]  # net[p1] == -net[p2]
        if abs(diff) < 1e-9:
            summary = {"info": "Both are settled up"}
        elif diff > 0:
            summary = {p2: f"owes {p1} {abs(diff):.2f}"}
        else:
            summary = {p1: f"owes {p2} {abs(diff):.2f}"}

    else:
        # n > 2: equal-split among everyone except the payer
        for e in expenses:
            payer = e.get("payer")
            amt = float(e.get("amount", 0) or 0)
            if payer not in net:
                continue
            if n - 1 <= 0:
                continue
            share = amt / (n - 1)
            for person in participants:
                if person == payer:
                    net[person] += amt  # they fronted the cash
                else:
                    net[person] -= share  # each non-payer owes their share

        # Build a concise multi-person summary: list who owes/owed (net)
        creditors = {p: v for p, v in net.items() if v > 1e-9}
        debtors   = {p: -v for p, v in net.items() if v < -1e-9}
        if not creditors and not debtors:
            summary = {"info": "All settled"}
        else:
            # human-friendly lines, e.g., {"Agnes": "is owed 120.00", "Brian": "owes 120.00", ...}
            lines = {}
            for p, v in sorted(creditors.items(), key=lambda x: -x[1]):
                lines[p] = f"is owed {v:.2f}"
            for p, v in sorted(debtors.items(), key=lambda x: -x[1]):
                lines[p] = f"owes {v:.2f}"
            summary = lines

    data["balances"] = {p: round(v, 2) for p, v in net.items()}
    data["summary"] = summary


# ==================== FEATURES ====================

def add_expense(file_name, data):
    participants = data.get("participants", [])
    if len(participants) < 2:
        err("Need at least 2 participants to add an expense.")
        return

    sec("Who paid?")
    for i, p in enumerate(participants, 1):
        print(f"{i}. {p}")

    choice = input("Choice: ").strip()
    if not choice.isdigit() or not (1 <= int(choice) <= len(participants)):
        err("Invalid choice.")
        return
    payer = participants[int(choice) - 1]

    try:
        amount = float(input("Enter amount: ").strip())
    except ValueError:
        err("Invalid amount.")
        return

    desc = input("Enter description (optional): ").strip()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    data.setdefault("expenses", []).append({
        "payer": payer,
        "amount": amount,
        "description": desc,
        "time": timestamp
    })

    ok(f"Expense added: {payer} paid {amount:.2f} for {desc if desc else 'N/A'} at {timestamp}")

    # Auto update & save; also show fresh balance line
    save_data(file_name, data)
    show_current_balance(data)


def show_current_balance(data):
    participants = data.get("participants", [])
    n = len(participants)
    balances = data.get("balances", {})

    if n == 2:
        p1, p2 = participants[0], participants[1]
        diff = balances.get(p1, 0)
        print(Fore.MAGENTA + "\n--- Balance ---")
        if abs(diff) < 1e-9:
            print("Both are settled up.")
        elif diff > 0:
            print(f"{p2} owes {p1} {abs(diff):.2f}")
        else:
            print(f"{p1} owes {p2} {abs(diff):.2f}")
    else:
        print(Fore.MAGENTA + "\n--- Balances ---")
        for p in participants:
            v = balances.get(p, 0.0)
            if v > 0:
                print(Fore.GREEN + f"{p} is owed {v:.2f}")
            elif v < 0:
                print(Fore.RED + f"{p} owes {-v:.2f}")
            else:
                print(Fore.YELLOW + f"{p} is settled.")


def calculate_balances(file_name, data):
    update_summary(data)
    save_data(file_name, data)
    show_current_balance(data)


def view_expenses(data):
    exps = data.get("expenses", [])
    if not exps:
        info("No expenses recorded yet.")
        return
    sec("All Expenses")
    for i, e in enumerate(exps, 1):
        payer = e.get("payer", "?")
        amt = e.get("amount", 0.0)
        desc = e.get("description", "")
        t = e.get("time", "")
        print(f"{i}. {payer} paid {amt:.2f} for {desc if desc else 'N/A'} on {t}")


# ==================== GROUPS / MENUS ====================

def create_group():
    group_name = input("Enter name for new group: ").strip()
    if not group_name:
        err("Group name cannot be empty.")
        return None, None
    file_name = group_name + ".json"

    participants = []
    sec("Enter participant names (press Enter on empty line to finish)")
    while True:
        name = input(f"Participant {len(participants)+1}: ").strip()
        if name == "":
            if len(participants) >= 2:
                break
            else:
                err("At least 2 participants required.")
                continue
        if name in participants:
            err("Duplicate name. Enter a unique name.")
            continue
        participants.append(name)

    data = {"participants": participants, "expenses": [], "balances": {}, "summary": {}}
    save_data(file_name, data)
    ok(f"Group '{group_name}' created with {len(participants)} participants.")
    return file_name, data

def select_group():
    while True:
        sec("Select Group")
        groups = list_groups()
        if groups:
            print("Available groups:")
            for i, g in enumerate(groups, 1):
                print(f"  {i}. {g[:-5]}")
        else:
            info("No groups found.")

        print("  N. Create new group")
        print("  Q. Quit")

        choice = input("Choice: ").strip().lower()
        if choice == "q":
            return None, None
        if choice == "n":
            return create_group()
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(groups):
                fn = groups[idx - 1]
                return fn, load_data(fn)
        err("Invalid choice.")

def main_menu(file_name, data):
    while True:
        sec(f"Main Menu ({file_name[:-5]})")
        print("1. Add Expense")
        print("2. View Expenses")
        print("3. Calculate Balances")
        print("4. Switch Group")
        print("5. Exit")
        choice = input("Select option: ").strip()

        if choice == "1":
            add_expense(file_name, data)
        elif choice == "2":
            view_expenses(data)
        elif choice == "3":
            calculate_balances(file_name, data)
        elif choice == "4":
            save_data(file_name, data)
            info("Switching group…")
            return  # back to group selector
        elif choice == "5":
            save_data(file_name, data)
            ok("Goodbye 👋")
            raise SystemExit
        else:
            err("Invalid choice.")


# ==================== RUN ====================

if __name__ == "__main__":
    banner()
    while True:
        fn, data = select_group()
        if not fn:
            ok("Exiting. 👋")
            break
        main_menu(fn, data)
