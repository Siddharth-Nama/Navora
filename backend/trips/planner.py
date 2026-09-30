DRIVING_LIMIT_HOURS = 11
DUTY_WINDOW_HOURS = 14
BREAK_AFTER_DRIVING_HOURS = 8
BREAK_HOURS = 0.5
RESET_HOURS = 10
CYCLE_LIMIT_HOURS = 70
RESTART_HOURS = 34
PICKUP_HOURS = 1
DROPOFF_HOURS = 1
FUEL_EVERY_MILES = 1000
FUEL_STOP_HOURS = 0.5
DRIVING = "driving"
ON_DUTY = "on_duty"
OFF_DUTY = "off_duty"


def make_event(status, start, end, miles, label):
    return {
        "status": status,
        "start": start,
        "end": end,
        "miles": miles,
        "label": label,
    }


def fuel_stop_miles(total_miles):
    stops = []
    mile = FUEL_EVERY_MILES
    while mile < total_miles:
        stops.append(mile)
        mile += FUEL_EVERY_MILES
    return stops


def fuel_stop_event(start, mile):
    end = start + FUEL_STOP_HOURS
    return make_event(
        ON_DUTY,
        start,
        end,
        mile,
        f"Fuel stop at mile {mile}",
    )


class DriverClocks:
    def __init__(self, cycle_used=0):
        self.time = 0.0
        self.drive = 0.0
        self.window = 0.0
        self.since_break = 0.0
        self.cycle = float(cycle_used)

    def add_drive(self, hours):
        self.time += hours
        self.drive += hours
        self.window += hours
        self.since_break += hours
        self.cycle += hours

    def add_on_duty(self, hours):
        self.time += hours
        self.window += hours
        self.cycle += hours

    def add_off_duty(self, hours):
        self.time += hours
        if hours >= RESET_HOURS:
            self.drive = 0.0
            self.window = 0.0
            self.since_break = 0.0
        if hours >= RESTART_HOURS:
            self.cycle = 0.0

    def snapshot(self):
        return {
            "time": self.time,
            "drive": self.drive,
            "window": self.window,
            "since_break": self.since_break,
            "cycle": self.cycle,
        }

    def drive_until_limit(self):
        remaining = [
            DRIVING_LIMIT_HOURS - self.drive,
            DUTY_WINDOW_HOURS - self.window,
            BREAK_AFTER_DRIVING_HOURS - self.since_break,
            CYCLE_LIMIT_HOURS - self.cycle,
        ]
        hours = min(remaining)
        return 0.0 if hours <= 0 else hours

    def needs_break(self):
        return self.since_break >= BREAK_AFTER_DRIVING_HOURS

    def take_break(self):
        start = self.time
        self.time += BREAK_HOURS
        self.window += BREAK_HOURS
        self.since_break = 0.0
        return make_event(
            OFF_DUTY,
            start,
            self.time,
            0,
            "30-minute break",
        )

    def hit_driving_limit(self):
        return self.drive >= DRIVING_LIMIT_HOURS

    def hit_duty_window(self):
        return self.window >= DUTY_WINDOW_HOURS

    def stop_reason(self):  # sourcery skip: assign-if-exp, reintroduce-else
        if self.since_break >= BREAK_AFTER_DRIVING_HOURS:
            return "break"
        if self.drive >= DRIVING_LIMIT_HOURS:
            return "driving_limit"
        if self.window >= DUTY_WINDOW_HOURS:
            return "duty_window"
        if self.cycle >= CYCLE_LIMIT_HOURS:
            return "cycle"
        return None

    def take_reset(self):
        start = self.time
        self.add_off_duty(RESET_HOURS)
        return make_event(
            OFF_DUTY,
            start,
            self.time,
            0,
            "10-hour reset",
        )

    def hit_cycle(self):
        return self.cycle >= CYCLE_LIMIT_HOURS

    def take_restart(self):
        start = self.time
        self.add_off_duty(RESTART_HOURS)
        return make_event(
            OFF_DUTY,
            start,
            self.time,
            0,
            "34-hour cycle restart",
        )

    def take_pickup(self, miles):
        start = self.time
        self.add_on_duty(PICKUP_HOURS)
        return make_event(
            ON_DUTY,
            start,
            self.time,
            miles,
            "Pickup",
        )

    def take_dropoff(self, miles):
        start = self.time
        self.add_on_duty(DROPOFF_HOURS)
        return make_event(
            ON_DUTY,
            start,
            self.time,
            miles,
            "Dropoff",
        )


def _ensure_on_duty_room(clocks, events, hours, miles):
    while True:
        window_left = DUTY_WINDOW_HOURS - clocks.window
        cycle_left = CYCLE_LIMIT_HOURS - clocks.cycle
        if window_left >= hours and cycle_left >= hours:
            return
        event = (
            clocks.take_restart()
            if cycle_left < hours
            else clocks.take_reset()
        )
        event["miles"] = miles
        events.append(event)


def _drive_leg(clocks, events, miles, hours, total_miles, fuel_marks, label):
    if miles <= 0:
        return total_miles
    if hours <= 0:
        hours = miles / 55.0
    speed = miles / hours
    left_miles = miles

    while left_miles > 1e-6:
        allowed = clocks.drive_until_limit()
        if allowed <= 0:
            reason = clocks.stop_reason()
            if reason == "break" and DUTY_WINDOW_HOURS - clocks.window >= BREAK_HOURS:
                event = clocks.take_break()
            elif reason == "cycle":
                event = clocks.take_restart()
            else:
                event = clocks.take_reset()
            event["miles"] = total_miles
            events.append(event)
        else:
            candidates = [
                mark
                for mark in fuel_marks
                if total_miles < mark <= total_miles + left_miles
            ]
            next_fuel = min(candidates, default=None)

            chunk_miles = min(left_miles, allowed * speed)
            if next_fuel is not None:
                chunk_miles = min(chunk_miles, next_fuel - total_miles)
            if chunk_miles <= 0:
                event = clocks.take_reset()
                event["miles"] = total_miles
                events.append(event)
            else:
                chunk_hours = chunk_miles / speed
                start = clocks.time
                clocks.add_drive(chunk_hours)
                total_miles += chunk_miles
                left_miles -= chunk_miles
                events.append(
                    make_event(DRIVING, start, clocks.time, total_miles, label)
                )

                if next_fuel is not None and abs(total_miles - next_fuel) < 1e-6:
                    _ensure_on_duty_room(
                        clocks, events, FUEL_STOP_HOURS, total_miles
                    )
                    start = clocks.time
                    clocks.add_on_duty(FUEL_STOP_HOURS)
                    events.append(
                        make_event(
                            ON_DUTY,
                            start,
                            clocks.time,
                            total_miles,
                            f"Fuel stop at mile {int(next_fuel)}",
                        )
                    )

    return total_miles


def build_timeline(distance, cycle_used=0):
    clocks = DriverClocks(cycle_used)
    events = []
    total_miles = 0.0
    fuel_marks = fuel_stop_miles(distance["miles"])
    legs = distance["legs"]

    total_miles = _drive_leg(
        clocks,
        events,
        legs[0]["miles"],
        legs[0]["minutes"] / 60,
        total_miles,
        fuel_marks,
        "Drive to pickup",
    )
    _ensure_on_duty_room(clocks, events, PICKUP_HOURS, total_miles)
    events.append(clocks.take_pickup(total_miles))

    total_miles = _drive_leg(
        clocks,
        events,
        legs[1]["miles"],
        legs[1]["minutes"] / 60,
        total_miles,
        fuel_marks,
        "Drive to dropoff",
    )
    _ensure_on_duty_room(clocks, events, DROPOFF_HOURS, total_miles)
    events.append(clocks.take_dropoff(total_miles))

    return events, clocks


def split_daily_logs(events):
    if not events:
        return []

    end_time = max(event["end"] for event in events)
    day_count = max(1, int(end_time // 24) + (1 if end_time % 24 else 0))
    if end_time == 0:
        day_count = 1

    logs = []
    for day in range(day_count):
        day_start = day * 24
        day_end = day_start + 24
        segments = [
            {
                "status": event["status"],
                "start": max(event["start"], day_start) - day_start,
                "end": min(event["end"], day_end) - day_start,
                "miles": event["miles"],
                "label": event["label"],
            }
            for event in events
            if event["end"] > day_start and event["start"] < day_end
        ]
        logs.append(
            {
                "day": day + 1,
                "start_hour": day_start,
                "segments": segments,
            }
        )
    return logs


def summarize_trip(events, distance, clocks):
    drive_hours = sum(
        event["end"] - event["start"]
        for event in events
        if event["status"] == DRIVING
    )
    fuel_stops = sum(1 for event in events if event["label"].startswith("Fuel"))
    resets = sum(1 for event in events if event["label"] == "10-hour reset")
    restarts = sum(
        1 for event in events if event["label"] == "34-hour cycle restart"
    )
    breaks = sum(1 for event in events if event["label"] == "30-minute break")
    days = len(split_daily_logs(events))
    warnings = []
    if breaks:
        warnings.append(f"{breaks} required 30-minute break(s).")
    if resets:
        warnings.append(f"{resets} 10-hour reset(s).")
    if restarts:
        warnings.append(f"{restarts} 34-hour cycle restart(s).")
    if fuel_stops:
        warnings.append(f"{fuel_stops} fuel stop(s).")
    return {
        "miles": round(distance["miles"], 1),
        "drive_hours": round(drive_hours, 2),
        "total_hours": round(clocks.time, 2),
        "days": days,
        "fuel_stops": fuel_stops,
        "warnings": warnings,
    }