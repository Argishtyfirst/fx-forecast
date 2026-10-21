import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { fixtures } from "../mocks";
import { bankTakeaway, MeetingStudy } from "./MeetingStudy";

const eurusd = fixtures.meetings.EURUSD;
const euramd = fixtures.meetings.EURAMD;

describe("MeetingStudy", () => {
  it("titles the study for the pair", () => {
    render(<MeetingStudy study={euramd} pairLabel="EUR/AMD" />);
    expect(screen.getByRole("heading", { name: "How EUR/AMD moved around meetings, last 12 months" })).toBeInTheDocument();
  });

  it("says how big the Fed move was and how often it followed the signal (EUR/USD)", () => {
    render(<MeetingStudy study={eurusd} pairLabel="EUR/USD" />);
    expect(screen.getByTestId("study-takeaway-FED")).toHaveTextContent(
      "Fed meetings: EUR/USD moved 0.51% on average, about 3× a normal day, followed the surprise or tone 5 of 8 times (small sample, 8 meetings).",
    );
  });

  it("says there is no expected direction when the bank's currency is in neither leg (Fed on EUR/AMD)", () => {
    render(<MeetingStudy study={euramd} pairLabel="EUR/AMD" />);
    expect(screen.getByTestId("study-takeaway-FED")).toHaveTextContent(
      "Fed meetings: EUR/AMD moved 0.60% on average, about 3× a normal day, no expected direction (small sample, 8 meetings).",
    );
    expect(screen.getByTestId("study-takeaway-ECB")).toHaveTextContent(/^ECB meetings: EUR\/AMD moved 0\.38% on average, about 1\.9× a normal day, followed the surprise or tone \d of \d times/);
    expect(screen.getByTestId("study-takeaway-CBA")).toHaveTextContent("CBA meetings");
  });

  it("drops the small-sample note from 10 meetings", () => {
    const b = { ...eurusd.banks[0], n: 12 };
    expect(bankTakeaway(b, "EUR/USD", eurusd.meetings)).not.toMatch(/small sample/);
  });

  it("draws one mark per meeting, a zero line and the normal-day band", () => {
    const { container } = render(<MeetingStudy study={euramd} pairLabel="EUR/AMD" />);
    expect(screen.getAllByTestId("study-mark")).toHaveLength(euramd.meetings.length);
    expect(container.querySelector(".study-zero")).not.toBeNull();
    expect(container.querySelector(".study-normal")).not.toBeNull();
    expect(screen.getByTestId("study-chart")).toHaveAttribute("aria-label", expect.stringContaining("Normal day move about"));
  });

  it("puts the selected bank in the accent and mutes the others", () => {
    render(<MeetingStudy study={euramd} pairLabel="EUR/AMD" focusBank="CBA" />);
    const marks = screen.getAllByTestId("study-mark");
    expect(marks.filter((m) => m.classList.contains("is-focus")).every((m) => m.dataset.bank === "CBA")).toBe(true);
    expect(marks.filter((m) => m.dataset.bank === "FED").every((m) => m.classList.contains("is-muted"))).toBe(true);
  });

  it("reads each meeting with the keyboard: date, surprise, tone and the three moves", async () => {
    render(<MeetingStudy study={euramd} pairLabel="EUR/AMD" />);
    const frame = screen.getByLabelText(/meeting reactions/);
    frame.focus();
    await userEvent.keyboard("{End}");
    const latest = euramd.meetings[0];
    const readout = document.querySelector(".study-readout")!;
    expect(readout).toHaveTextContent(latest.bank === "CBA" ? "CBA, 6 Oct 2026" : latest.date);
    expect(readout).toHaveTextContent(/run-up .*reaction .*follow-through/);
  });

  it("lists the meetings most recent first, with the disclaimer", () => {
    render(<MeetingStudy study={euramd} pairLabel="EUR/AMD" />);
    const rows = within(screen.getByTestId("study-table")).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(euramd.meetings.length);
    expect(rows[0]).toHaveTextContent("6 Oct 2026");
    expect(within(screen.getByTestId("meeting-study")).getByTestId("disclaimer")).toHaveTextContent(
      "Statistical estimate. Not financial advice.",
    );
  });
});
