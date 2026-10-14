import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { bandFor, PriorityScoreCell, ScoreBand, ScoreValue } from "./scoring"

describe("bandFor", () => {
  it("returns null for a null/missing score, never a fabricated band", () => {
    expect(bandFor(null)).toBeNull()
  })
  it("bands >=70 as High, >=40 as Medium, else Low", () => {
    expect(bandFor(85)).toBe("High")
    expect(bandFor(70)).toBe("High")
    expect(bandFor(55)).toBe("Medium")
    expect(bandFor(40)).toBe("Medium")
    expect(bandFor(10)).toBe("Low")
    expect(bandFor(0)).toBe("Low")
  })
})

describe("ScoreBand", () => {
  it("renders 'Not yet assessed' for a null score, never Low or 0", () => {
    render(<ScoreBand score={null} />)
    expect(screen.getByText("Not yet assessed")).toBeInTheDocument()
    expect(screen.queryByText("Low")).not.toBeInTheDocument()
    expect(screen.queryByText("0")).not.toBeInTheDocument()
  })
  it("renders the real band for a judged score", () => {
    render(<ScoreBand score={82} />)
    expect(screen.getByText("High")).toBeInTheDocument()
  })
})

describe("ScoreValue", () => {
  it("renders 'Not yet assessed' for a null dimension score", () => {
    render(<ScoreValue label="Reach" score={null} />)
    expect(screen.getByText("Not yet assessed")).toBeInTheDocument()
  })
})

describe("PriorityScoreCell", () => {
  it("renders 'Not yet assessed' when priority_score is null (e.g. one dimension still missing)", () => {
    render(<PriorityScoreCell score={null} scoringVersion={null} />)
    expect(screen.getByText("Not yet assessed")).toBeInTheDocument()
  })
  it("renders the real computed score once every dimension is judged", () => {
    render(<PriorityScoreCell score={57} scoringVersion="v1" />)
    expect(screen.getByText("57.0")).toBeInTheDocument()
  })
})
