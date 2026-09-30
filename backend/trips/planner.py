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