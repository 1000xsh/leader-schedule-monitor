import json
import time
import requests
import subprocess
import os
from datetime import datetime, timedelta
import argparse
import sys
import shutil
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.progress import Progress, BarColumn, TextColumn

console = Console()


def get_future_leader_slots(schedule, slot_duration):
    current_slot = get_current_slot()
    future_slots = []
    for slot in schedule:
        if slot["slot"] >= current_slot and slot["status"] == "pending":
            slot_start_time = datetime.now() + timedelta(
                seconds=(slot["slot"] - current_slot) * slot_duration
            )
            slot_end_time = slot_start_time + timedelta(seconds=slot_duration)
            future_slots.append(
                {
                    "slot": slot["slot"],
                    "start_time": slot_start_time,
                    "end_time": slot_end_time,
                }
            )
    # sort future_slots by 'start_time'
    future_slots.sort(key=lambda x: x["start_time"])
    return future_slots


def find_suitable_timeframes(future_slots, slot_duration):
    suitable_timeframes = []
    current_time = datetime.now()
    current_slot = get_current_slot()

    # combine future_slots into a list of occupied intervals
    occupied_intervals = []
    for slot in future_slots:
        start_time = slot["start_time"]
        end_time = slot["end_time"]
        start_slot = slot["slot"]
        end_slot = slot["slot"]
        occupied_intervals.append(
            {
                "start_time": start_time,
                "end_time": end_time,
                "start_slot": start_slot,
                "end_slot": end_slot,
            }
        )

    # find gaps between occupied intervals
    if not occupied_intervals:
        # no future leader slots, the entire future is a suitable timeframe
        # for practicality, limit to next 24 hours
        future_limit_time = current_time + timedelta(hours=24)
        future_limit_slot = current_slot + int(24 * 3600 / slot_duration)
        suitable_timeframes.append(
            {
                "start_slot": current_slot,
                "end_slot": future_limit_slot,
                "start_time": current_time,
                "end_time": future_limit_time,
                "duration": future_limit_time - current_time,
            }
        )
    else:
        # check for gap before the first occupied interval
        if occupied_intervals[0]["start_time"] > current_time:
            suitable_timeframes.append(
                {
                    "start_slot": current_slot,
                    "end_slot": occupied_intervals[0]["start_slot"] - 1,
                    "start_time": current_time,
                    "end_time": occupied_intervals[0]["start_time"],
                    "duration": occupied_intervals[0]["start_time"] - current_time,
                }
            )
        # check gaps between intervals
        for i in range(len(occupied_intervals) - 1):
            end_time_current = occupied_intervals[i]["end_time"]
            start_time_next = occupied_intervals[i + 1]["start_time"]
            end_slot_current = occupied_intervals[i]["end_slot"]
            start_slot_next = occupied_intervals[i + 1]["start_slot"]
            if start_time_next > end_time_current:
                suitable_timeframes.append(
                    {
                        "start_slot": end_slot_current + 1,
                        "end_slot": start_slot_next - 1,
                        "start_time": end_time_current,
                        "end_time": start_time_next,
                        "duration": start_time_next - end_time_current,
                    }
                )
        # optional check for gap after last occupied interval
        future_limit_time = occupied_intervals[-1]["end_time"] + timedelta(hours=1)
        future_limit_slot = occupied_intervals[-1]["end_slot"] + int(
            3600 / slot_duration
        )
        suitable_timeframes.append(
            {
                "start_slot": occupied_intervals[-1]["end_slot"] + 1,
                "end_slot": future_limit_slot,
                "start_time": occupied_intervals[-1]["end_time"],
                "end_time": future_limit_time,
                "duration": future_limit_time - occupied_intervals[-1]["end_time"],
            }
        )

    # sort the timeframes by duration, descending
    suitable_timeframes.sort(key=lambda x: x["duration"], reverse=True)

    # return the top 5
    return suitable_timeframes[:5]


def get_next_leader_timeframes(
    schedule, slot_duration, num_timeframes=5, slots_per_timeframe=4
):
    current_slot = get_current_slot()
    future_leader_slots = [
        slot
        for slot in schedule
        if slot["slot"] >= current_slot and slot["status"] == "pending"
    ]
    future_leader_slots.sort(key=lambda x: x["slot"])

    # group slots into timeframes of slots_per_timeframe
    grouped_timeframes = []
    for i in range(0, len(future_leader_slots), slots_per_timeframe):
        timeframe_slots = future_leader_slots[i : i + slots_per_timeframe]
        if len(timeframe_slots) > 0:
            start_slot = timeframe_slots[0]["slot"]
            end_slot = timeframe_slots[-1]["slot"]
            start_time = datetime.now() + timedelta(
                seconds=(start_slot - current_slot) * slot_duration
            )
            end_time = datetime.now() + timedelta(
                seconds=(end_slot - current_slot + 1) * slot_duration
            )
            duration = end_time - start_time
            grouped_timeframes.append(
                {
                    "start_slot": start_slot,
                    "end_slot": end_slot,
                    "start_time": start_time,
                    "end_time": end_time,
                    "duration": duration,
                }
            )
    # return the next num_timeframes
    return grouped_timeframes[:num_timeframes]


def create_display(
    schedule, slot_duration, validator_identity, progress, task_id, start_time
):
    layout = Layout()
    layout.split(Layout(name="main", ratio=2), Layout(name="footer", size=3))

    current_slot = get_current_slot()
    next_slot = next((slot for slot in schedule if slot["slot"] > current_slot), None)

    # main content: leader schedule information
    main_table = Table(show_header=False, expand=True)
    main_table.add_column("key", style="cyan", width=30)
    main_table.add_column("value", style="bright_white")

    main_table.add_row("current Slot", str(current_slot))

    # handle the next leader slot info
    if next_slot:
        slots_difference = next_slot["slot"] - current_slot
        time_until_next_slot = slots_difference * slot_duration
        next_slot_time = datetime.now() + timedelta(seconds=time_until_next_slot)
        main_table.add_row(
            "next leader slot",
            f"[bright_white]{next_slot['slot']} at {next_slot_time.strftime('%Y-%m-%d %H:%M:%S')}[/bright_white]",
        )
        main_table.add_row(
            "time until next leader slot",
            f"[green]{timedelta(seconds=int(time_until_next_slot))}[/green]",
        )

        # update progress bar
        elapsed_time = (datetime.now() - start_time).total_seconds()
        total_time = (next_slot_time - start_time).total_seconds()
        progress.update(task_id, completed=elapsed_time, total=total_time)

        # add progress to main table
        progress_table = Table.grid(expand=True)
        progress_table.add_column(ratio=30)
        progress_table.add_row(progress)
        main_table.add_row("progress", progress_table)
    else:
        main_table.add_row("next Leader Slot", "No upcoming leader slots found")

    block_production = get_block_production(validator_identity)
    if block_production:
        total_leader_slots = len(schedule)
        produced_slots = block_production["byIdentity"][validator_identity][0]
        leader_slots_done = block_production["byIdentity"][validator_identity][1]
        skipped_slots = max(0, produced_slots - leader_slots_done)

        # calculate production stats
        produced_percentage = (
            (produced_slots / total_leader_slots) * 100 if total_leader_slots > 0 else 0
        )
        skipped_percentage = (
            (skipped_slots / leader_slots_done) * 100 if leader_slots_done > 0 else 0
        )

        # add rows to the table
        main_table.add_row(
            "pending Slots",
            str(sum(1 for slot in schedule if slot["status"] == "pending")),
        )
        main_table.add_row(
            "skipped | produced | pending | total",
            f"[bright_white]{skipped_slots} ({skipped_percentage:.2f}%) | {produced_slots - skipped_slots} | {str(sum(1 for slot in schedule if slot['status'] == 'pending'))} | {total_leader_slots}",
        )
    else:
        main_table.add_row("block production", "error: error fetching block production")

    # calculate future leader slots
    future_slots = get_future_leader_slots(schedule, slot_duration)
    # find suitable timeframes
    suitable_timeframes = find_suitable_timeframes(future_slots, slot_duration)

    # format suitable timeframes as a string, including slot ranges
    if suitable_timeframes:
        timeframes_str = "\n\n".join(
            [
                f"Slots {tf['start_slot']} - {tf['end_slot']}\n{tf['start_time'].strftime('%Y-%m-%d %H:%M:%S')} - {tf['end_time'].strftime('%Y-%m-%d %H:%M:%S')} ({str(tf['duration']).split('.')[0]})"
                for tf in suitable_timeframes
            ]
        )
    else:
        timeframes_str = "No suitable timeframes found"

    # add to main_table
    main_table.add_row("top 5 suitable timeframes", timeframes_str)

    # get next leader timeframes
    next_leader_timeframes = get_next_leader_timeframes(
        schedule, slot_duration, num_timeframes=5, slots_per_timeframe=4
    )

    # gormat next leader timeframes as a string
    if next_leader_timeframes:
        leader_timeframes_str = "\n\n".join(
            [
                f"Slots {tf['start_slot']} - {tf['end_slot']}\n{tf['start_time'].strftime('%Y-%m-%d %H:%M:%S')} - {tf['end_time'].strftime('%Y-%m-%d %H:%M:%S')} ({str(tf['duration']).split('.')[0]})"
                for tf in next_leader_timeframes
            ]
        )
    else:
        leader_timeframes_str = "no upcoming leader timeframes found"

    # add to main_table
    main_table.add_row("next leader timeframes", leader_timeframes_str)

    # update layout
    layout["main"].update(Panel(main_table, title="leader schedule information"))

    return layout


def get_validator_identity():
    parser = argparse.ArgumentParser(description="solana schedule monitor")
    parser.add_argument("-i", "--identity", required=True, help="validator identity")
    args = parser.parse_args()
    return args.identity


def get_block_production(validator_identity):
    url = "https://api.mainnet-beta.solana.com"
    headers = {"Content-Type": "application/json"}
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBlockProduction",
        "params": [{"identity": validator_identity}],
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        return data["result"]["value"]
    except requests.RequestException as e:
        print(f"error fetching block production: {e}")
        return None


def download_leader_schedule():
    file_path = "leader_schedule.json"
    if os.path.exists(file_path):
        print(f"found existing {file_path}")
        return True

    print(f"{file_path} not found. attempting to fetch...")
    try:
        url = "https://api.mainnet-beta.solana.com"
        headers = {"Content-Type": "application/json"}
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getLeaderSchedule",
            "params": [None, {"identity": get_validator_identity()}],
        }
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

        if "result" in data and data["result"] is not None:
            with open(file_path, "w") as f:
                json.dump(data["result"], f)
            print(f"successfully downloaded and saved {file_path}")
            return True
        else:
            print("error: received empty or invalid leader schedule from api")
            return False
    except requests.RequestException as e:
        print(f"error downloading leader schedule: {e}")
        return False


def calculate_slot_duration():
    url = "http://api.mainnet-beta.solana.com"
    headers = {"Content-Type": "application/json"}
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getRecentPerformanceSamples",
        "params": [1],
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        sample = data["result"][0]
        return sample["samplePeriodSecs"] / sample["numSlots"]
    except requests.RequestException as e:
        print(f"error fetching performance samples: {e}")
        return None


def get_current_slot():
    solana_path = shutil.which("solana")
    if not solana_path:
        print(
            "error: 'solana' command not found. please ensure sol cli is installed and in your path."
        )
        return None

    try:
        result = subprocess.run(
            [solana_path, "slot"], capture_output=True, text=True, check=True
        )
        return int(result.stdout.strip())
    except subprocess.CalledProcessError as e:
        print(f"error getting current slot: {e}")
        return None


def get_epoch_info():
    url = "http://api.mainnet-beta.solana.com"
    headers = {"Content-Type": "application/json"}
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getEpochInfo",
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        return data["result"]
    except requests.RequestException as e:
        print(f"error fetching epoch info: {e}")
        return None


def relative_slot_to_absolute(relative_slot, epoch_info):
    epoch_start_slot = epoch_info["absoluteSlot"] - epoch_info["slotIndex"]
    return epoch_start_slot + relative_slot


def calculate_schedule(validator_identity):
    try:
        with open("leader_schedule.json", "r") as f:
            schedule = json.load(f)

        if validator_identity not in schedule:
            print(f"no schedule found for validator {validator_identity}")
            return None

        epoch_info = get_epoch_info()
        if epoch_info is None:
            print("error: could not fetch epoch info")
            return None

        calculated_schedule = [
            {"slot": relative_slot_to_absolute(slot, epoch_info), "status": "pending"}
            for slot in schedule[validator_identity]
        ]

        calculated_schedule.sort(key=lambda x: x["slot"])

        with open("leader_schedule_calculated.json", "w") as f:
            json.dump(calculated_schedule, f)

        return calculated_schedule
    except json.JSONDecodeError as e:
        print(f"error decoding leader_schedule.json: {e}")
        return None
    except IOError as e:
        print(f"error reading or writing schedule files: {e}")
        return None


def update_schedule_status(schedule):
    current_slot = get_current_slot()
    if current_slot is None:
        print("warning: unable to get current slot. skipping status update.")
        return schedule

    updated = False
    for slot in schedule:
        if slot["slot"] < current_slot and slot["status"] == "pending":
            slot["status"] = "done"
            updated = True

    if updated:
        with open("leader_schedule_calculated.json", "w") as f:
            json.dump(schedule, f)

    return schedule


def monitor_schedule(validator_identity, schedule, slot_duration):
    progress = Progress(
        TextColumn("[bold blue]{task.fields[title]}", justify="right"),
        BarColumn(bar_width=30),
        "[progress.percentage]{task.percentage:>3.0f}%",
    )
    task_id = progress.add_task(
        "time until next slot", completed=0, total=100, title="next slot"
    )
    start_time = datetime.now()

    with Live(console=console, screen=True, refresh_per_second=1) as live:
        while True:
            schedule = update_schedule_status(schedule)
            display = create_display(
                schedule,
                slot_duration,
                validator_identity,
                progress,
                task_id,
                start_time,
            )
            live.update(display)
            time.sleep(2)  # update every xy seconds

            # check if we have next slot
            current_slot = get_current_slot()
            next_slot = next(
                (slot for slot in schedule if slot["slot"] > current_slot), None
            )
            if next_slot and current_slot >= next_slot["slot"]:
                # reset the progress bar
                start_time = datetime.now()
                progress.reset(task_id, completed=0, total=100)


def main():
    validator_identity = get_validator_identity()

    if not download_leader_schedule():
        console.print(
            "error: could not find or download leader_schedule.json", style="bold red"
        )
        sys.exit(1)

    schedule = calculate_schedule(validator_identity)
    if schedule is None:
        console.print("error: could not calculate schedule", style="bold red")
        sys.exit(1)

    slot_duration = calculate_slot_duration()
    if slot_duration is None:
        console.print(
            "warning: could not calculate slot duration. using default value of 0.4 seconds.",
            style="bold yellow",
        )
        slot_duration = 0.4  # default slot duration as a fallback

    try:
        monitor_schedule(validator_identity, schedule, slot_duration)
    except KeyboardInterrupt:
        console.print("\nexiting...", style="bold blue")


if __name__ == "__main__":
    main()
