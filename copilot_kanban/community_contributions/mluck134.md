## Product Direction

This application is a Supply Chain Workflow Tracker built on a Kanban structure.

Each card represents a real-world supply chain issue, task, or risk.

## Board Structure
- Single board with 5 columns
- Default column names:
  - Backlog
  - Identified
  - In Progress
  - Mitigation
  - Resolved
## Card (Node) Requirements
### On Board (Minimal View)
- Title only
- Optional flag indicator

## Card Interaction
- Clicking a card opens a right-side detail panel
- No modal popups
- Board remains visible

## Detail Panel Requirements
### Core Fields
- Editable title
- Editable description
### Supply Chain Context
- Type (shipment, inventory, production, supplier, other)
- Priority (low, medium, high)
- Owner (text)
### Attachments
- Add supporting documents (mocked, no backend)
- Store name and type only
### Flags / Highlights
- Only one active flag:
  - flagged
  - attention
  - critical
- Must display on card and panel
### Notes / Activity Log
- Append-only notes
- Simple text entries
- No editing required
## Constraints
- No persistence
- No authentication
- No real-time collaboration
- All state is in-memory
- 
## UX Principles
- Keep board visually clean
- Push complexity into detail panel
- Fast, smooth interactions
- No feature creep
