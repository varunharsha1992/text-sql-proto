# Feature Specification: CSV Upload and Automated Exploratory Data Analysis

**Feature Branch**: `001-upload-auto-eda`  
**Created**: 2026-04-17  
**Status**: Draft  
**Input**: User description: "$ARGUMENTS"

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Upload a CSV and See Instant Data Profile (Priority: P1)

A user has a CSV file they want to analyse. They land on the Upload screen, drop their file into the upload zone (or use the file picker), and within seconds the right-hand canvas populates with a rich summary of their data: how many rows and columns, how many nulls and duplicates, key distributions as charts, and flagged quality issues. No configuration, no manual steps — just upload and read.

**Why this priority**: This is the entry point to the entire application. Without a successful upload and profile, no subsequent screen can function. It is also the first demo moment: the audience should see immediate, substantive output from a single file drop.

**Independent Test**: Upload the demo CSV file. The canvas should populate with stat cards, at least 2 charts, and at least one quality warning — all without any user action beyond the upload itself.

**Acceptance Scenarios**:

1. **Given** the user is on the Upload screen with no file loaded, **When** they drag and drop a CSV file onto the upload zone, **Then** the system accepts the file, shows file metadata (name, row count, column count, file size), and begins analysis automatically.
2. **Given** a file has been uploaded and analysis is running, **When** the user waits, **Then** the right canvas shows a loading state, and within 60 seconds transitions to a completed analysis with stat cards, charts, and data quality warnings.
3. **Given** the analysis is complete, **When** the user views the canvas, **Then** they see at minimum: total row count, null cell count, duplicate row count, at least one chart, and any columns with >5% null values flagged as warnings.
4. **Given** the analysis is complete, **When** the user clicks "Continue to Context →", **Then** they are taken to Screen 2 (Context Agent) with their dataset context preserved.

---

### User Story 2 — Understand Data Quality at a Glance (Priority: P2)

Once the analysis completes, the user needs to quickly understand the health of their dataset before doing anything else. The canvas surfaces quality problems — high null rates, duplicate rows, outlier values, mixed data formats — as visible warnings so the user immediately knows what to expect downstream.

**Why this priority**: The quality summary is the key trust-building moment. A user who sees their data's issues before querying it is better prepared and more confident in the results. It also demonstrates agent intelligence — the system noticed things the user might have missed.

**Independent Test**: Upload the demo CSV. The canvas should display at least two warning items identifying specific columns with quality issues (e.g. null percentages, outliers), without the user having to ask or configure anything.

**Acceptance Scenarios**:

1. **Given** the uploaded CSV has columns with >5% null values, **When** the analysis completes, **Then** each such column is listed as a warning on the canvas with its null percentage.
2. **Given** the uploaded CSV has duplicate rows, **When** the analysis completes, **Then** the duplicate count is shown as an amber-coloured stat card.
3. **Given** the uploaded CSV has a numeric column with values that appear to be data entry errors (e.g. percentages >100), **When** the analysis completes, **Then** a warning is surfaced identifying the column and the nature of the issue.
4. **Given** the uploaded CSV has columns with mixed data formats (e.g. dates written two different ways), **When** the analysis completes, **Then** the system normalises them silently and does not surface a warning — format issues that were auto-corrected do not need user attention.

---

### User Story 3 — View Meaningful Charts Without Configuration (Priority: P3)

The canvas automatically selects appropriate chart types for each column based on the nature of the data: histograms for numeric distributions, bar charts for categorical breakdowns, scatter plots for correlated columns, line charts for time-series data. The user does not choose chart types or configure axes — the agent decides.

**Why this priority**: Charts are what make the analysis feel alive and impressive in a demo. They are not required for the pipeline to function, but they are the difference between a useful tool and an impressive one.

**Independent Test**: Upload the demo CSV. At least two charts should appear on the canvas, each with a title, appropriate axis labels, and data that matches the actual dataset.

**Acceptance Scenarios**:

1. **Given** the dataset has a numeric column with high cardinality, **When** the analysis completes, **Then** a histogram is shown for that column's distribution.
2. **Given** the dataset has a categorical column with 10 or fewer distinct values, **When** the analysis completes, **Then** a bar chart is shown with value counts.
3. **Given** the dataset has two strongly correlated numeric columns, **When** the analysis completes, **Then** a scatter plot is shown for those two columns.
4. **Given** the dataset has a date/time column and a numeric column, **When** the analysis completes, **Then** a line chart is shown plotting the numeric value over time.
5. **Given** the analysis is complete, **When** the canvas renders, **Then** no more than 5 charts are shown — the most informative are selected.

---

### Edge Cases

- What happens when the user uploads a file larger than 50MB? → System rejects it immediately with a clear error message before attempting any processing.
- What happens when the uploaded file is not a valid CSV (e.g. an Excel file, a PDF, an image)? → System rejects it with a clear error identifying the file type issue.
- What happens when the CSV has only one column or only one row? → System completes analysis with reduced output (fewer charts possible), does not error.
- What happens when every column has >50% null values? → System completes analysis and surfaces warnings for all affected columns; does not fail silently.
- What happens when the analysis agent encounters an unexpected error mid-run? → The job transitions to an error state, and the UI shows an error message with an option to retry.
- What happens if the user navigates away from Screen 1 while analysis is still running? → The job continues in the background; returning to Screen 1 shows the completed result if the job finished.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept CSV file uploads via drag-and-drop and file picker, with a maximum file size of 50MB.
- **FR-002**: System MUST reject non-CSV files and files exceeding 50MB with a clear, user-readable error message.
- **FR-003**: System MUST automatically begin dataset analysis immediately after a successful file upload, without requiring any user action.
- **FR-004**: System MUST display file metadata (filename, row count, column count, file size) on the left panel once the file is parsed.
- **FR-005**: System MUST show a loading/in-progress state on the right canvas while analysis is running.
- **FR-006**: System MUST display at minimum four summary stat cards: total rows, null cell count, duplicate row count, and date range (if a date column exists).
- **FR-007**: System MUST flag any column with more than 5% null values as a visible warning on the canvas, identifying the column name and percentage.
- **FR-008**: System MUST flag duplicate rows if any exist, shown as an amber-coloured indicator.
- **FR-009**: System MUST display between 1 and 5 charts automatically selected based on the data's characteristics, with titles and axis labels.
- **FR-010**: System MUST apply silent data type normalisation at parse time (stripping currency symbols, normalising mixed date formats) without surfacing these as errors to the user.
- **FR-011**: System MUST enable the "Continue to Context →" navigation button only after analysis has fully completed.
- **FR-012**: System MUST persist the upload identifier across screens so that subsequent screens (Context Agent, Query Canvas) can reference the same dataset.
- **FR-013**: System MUST show an error state on the canvas if analysis fails, with an option to retry.
- **FR-014**: System MUST complete analysis and display results within 60 seconds of file upload for a dataset up to 50MB.

### Key Entities

- **Upload**: Represents a single CSV file submission. Has a unique identifier, a human-readable slug derived from the filename, file metadata (row count, column count, size), and a timestamp.
- **Analysis Job**: Tracks the lifecycle of the automated analysis process. Has a status (pending / running / done / error), links to the Upload, and stores the completed analysis result when done.
- **Canvas Response**: The structured output of the analysis agent. Contains a list of insight items (stats, warnings), a list of chart specifications, and an optional results table. This is the single data contract the frontend renders.
- **Chart Specification**: Defines a single chart — its type, title, axis labels, and data points — in a format the frontend can render without knowing how it was generated.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can drop a CSV file and see analysis results appear on the canvas within 60 seconds, with no configuration required.
- **SC-002**: 100% of columns with more than 5% null values are surfaced as warnings in the analysis output.
- **SC-003**: At least 2 charts are generated for any dataset with more than 2 columns, selected automatically based on data characteristics.
- **SC-004**: The "Continue to Context" button is reliably disabled until analysis completes — users cannot proceed to the next screen with an incomplete analysis.
- **SC-005**: Analysis completes without error for any well-formed CSV up to 50MB, regardless of mixed formats, currency-prefixed numbers, or partially null columns.
- **SC-006**: The dataset identifier is correctly passed to all subsequent screens — no re-upload required to move through the application.

---

## Assumptions

- Users are uploading single-table CSV files (not multi-sheet or relational exports). Multi-table support is out of scope for this feature.
- The CSV uses a standard comma delimiter. Tab-separated or semicolon-separated files are out of scope.
- The application is single-user and runs locally — no concurrent upload handling or user session management is required.
- The demo dataset (messy e-commerce orders CSV) is the primary validation target. The feature must produce meaningful output for this dataset specifically.
- File storage is local disk. Cloud storage (S3/GCS) is not required for this version.
- The analysis agent has access to an LLM API (OpenAI GPT-4o). If the API is unavailable, the job will fail with an error — no fallback analysis mode is provided.
- The type normalisation step (currency stripping, date format unification) is applied silently and does not require user confirmation or review.
- The right-hand canvas is shared infrastructure used across all screens. Its rendering behaviour (stat cards, charts, warnings) is defined by the Canvas component specification.
