class EventRouter:

    def __init__(self, backends):

        self.backends = backends

    def dispatch(self, event):

        event_type = event["type"]

        if event_type == "solenoid":

            self.backends["solenoid"].pulse(
                event["target"],
                event["duration"]
            )

        elif event_type == "gear_rack":

            self.backends["gear_rack"].execute(
                event
            )

        else:

            print(
                f"Unknown event type: {event_type}"
            )
