"""Evaluation-only fault aliases and failure at the actual session booking write."""
from copy import deepcopy


def normalize_faults(values):
    if not isinstance(values, list): raise ValueError("fault array required")
    result = []
    for value in values:
        if not isinstance(value, dict): raise ValueError("fault object required")
        fault = deepcopy(value)
        if "times" in fault:
            if "attempts" in fault and fault["attempts"] != fault["times"]:
                raise ValueError("conflicting fault attempt aliases")
            fault["attempts"] = fault.pop("times")
        if set(fault) - {"tool", "mode", "attempts", "slot_id", "message", "code", "stage"}:
            raise ValueError("unsupported fault field")
        mode = str(fault.get("mode", "")).casefold().replace(" ", "_")
        if mode not in {"error", "slot_taken"} or fault.get("tool") not in {"resolve_options", "get_details", "find_slots", "book_appointment", "request_human_transfer"}:
            raise ValueError("unsupported fault mode/tool")
        fault["mode"] = mode
        stage = "write" if fault["tool"] == "book_appointment" else "tool_attempt"
        if fault.get("stage", stage) != stage: raise ValueError("fault stage mismatch")
        fault["stage"] = stage
        if mode == "slot_taken":
            if stage != "write" or not isinstance(fault.get("slot_id"), str): raise ValueError("slot loss requires booking write and slot")
            count = fault.get("attempts", 1)
            if type(count) is not int or count < 1: raise ValueError("positive slot-loss attempts required")
            fault["attempts"] = count
        else:
            if fault.get("attempts", "all") != "all": raise ValueError("error mode repeats on every attempt")
            fault["attempts"] = "all"
        result.append(fault)
    return result


class InjectedWriteFailure(RuntimeError):
    def __init__(self, result):
        self.result = result


class WriteFaultController:
    """Dict set occurs only after the original engine's booking guards succeed."""
    def __init__(self, engine, faults):
        self.engine = engine
        self.faults = normalize_faults(faults)
        self.events = []
        controller = self
        class Writes(dict):
            def __setitem__(self, slot_id, booking):
                controller.before_write(slot_id)
                super().__setitem__(slot_id, booking)
        engine._bookings = Writes(engine._bookings)

    def failure(self, index, slot_id=None, write=False):
        fault = self.faults[index]
        consent = bool(self.engine.state.confirmation is not None and self.engine.state.selected_slot_id == slot_id)
        result = {"status": "error", "tool": fault["tool"], "retryable": False,
                  "technical_failure": fault["mode"] == "error",
                  "code": fault.get("code", "slot_taken" if fault["mode"] == "slot_taken" else "injected_tool_error"),
                  "message": fault.get("message", "The slot was taken." if fault["mode"] == "slot_taken" else "The tool is unavailable.")}
        if slot_id: result["slot_id"] = slot_id
        self.events.append({"fault_index": index, "mode": fault["mode"], "tool": fault["tool"],
                            "stage": "write" if write else "tool_attempt", "triggered": True,
                            "after_consent": consent if write else None, "slot_id": slot_id})
        if fault["mode"] == "slot_taken": self.engine.mark_slot_unavailable(slot_id)
        return result

    def before_write(self, slot_id):
        for index, fault in enumerate(self.faults):
            if fault["stage"] == "write" and (fault["mode"] == "error" or fault["slot_id"] == slot_id):
                raise InjectedWriteFailure(self.failure(index, slot_id, write=True))

    def wrap(self, name, handler):
        from text_runner import TextToolFaultInjector
        async def wrapped(args, manager):
            for index, fault in enumerate(self.faults):
                if fault["stage"] == "tool_attempt" and fault["tool"] == name:
                    return self.failure(index)
            try:
                return await TextToolFaultInjector._invoke(handler, args, manager)
            except InjectedWriteFailure as error:
                return error.result  # Actual failure is visible to the unchanged model.
        return wrapped

    def evidence(self):
        return [{"fault_index": i, "intended_stage": fault["stage"],
                 "triggered": any(e["fault_index"] == i for e in self.events),
                 "write_after_consent": any(e["fault_index"] == i and e["stage"] == "write" and e["after_consent"] for e in self.events),
                 "trigger_count": sum(e["fault_index"] == i for e in self.events)} for i, fault in enumerate(self.faults)]
