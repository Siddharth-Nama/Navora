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
        if hours <= 0:
            return 0.0
        return hours