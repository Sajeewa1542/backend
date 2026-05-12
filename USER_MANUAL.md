# User Manual

This manual explains how to use the hybrid variation evaluation prototype as a beginner.

## 1. What This Software Does

The system helps you prepare a variation proposal for a construction project. It can:

- read uploaded BOQ, schedule, rate breakdown, and supporting documents
- find likely matches for items, rates, and activities
- let you confirm the correct evidence before evaluation
- calculate the cost impact and time impact
- generate a PDF proposal with formulas and supporting notes

The AI part only helps with extraction and matching. The final calculation is done by the rule-based engine after you confirm the data.

## 2. Who Should Use It

This tool is intended for:

- quantity surveyors
- project engineers
- contract administrators
- students or researchers who want to study variation evaluation workflows

## 3. Before You Start

Make sure you have:

- a web browser
- the backend server running
- the frontend application running
- your project files ready, such as BOQ, schedule, rate breakdown, quotations, or instructions

If you run the project locally, you may also need:

- Python 3.10 or newer
- Node.js 18 or newer
- Tesseract OCR for scanned PDF reading
- a Groq API key if you use the AI-assisted extraction features

## 4. Starting the Application

You can start the project in two ways.

### Option A: Docker

1. Install Docker Desktop.
2. Create the backend `.env` file and add your API key.
3. Run `docker-compose up --build` from the project root.
4. Open the frontend in your browser.

### Option B: Local Development

1. Start the backend service.
2. Start the frontend app.
3. Open the frontend URL shown in the terminal.

## 5. First-Time Workflow

Follow these steps for a simple end-to-end use case:

1. Open the application.
2. Create or select a project.
3. Upload the main documents:
   - BOQ file
   - schedule or master programme
   - rate breakdown file
4. Upload any extra supporting files if you have them.
5. Open the chat or evaluation screen and describe the variation in plain language.
6. Review the extracted candidates shown by the system.
7. Confirm the correct BOQ item, rate source, and activity.
8. Choose the variation mode, such as omission, addition, or substitution.
9. Click the confirm and evaluate button.
10. Review the result page.
11. Download the PDF proposal if you need a document for sharing or review.

## 6. Understanding the Screens

### Welcome Screen

This is the starting page. It explains the project and guides you to upload or continue a session.

### Upload Screen

Use this page to upload your BOQ, schedule, rate breakdown, and supporting files.

### Chat / Confirmation Screen

This page shows the extracted candidates. You should check whether the suggested BOQ item, rate source, and activity are correct before continuing.

### Sessions Screen

This page helps you return to previous projects or sessions.

### Proposal Screen

This page shows the final calculation, validation notes, and PDF download option.

## 7. What You Should Check Before Confirming

Before you click confirm, make sure:

- the BOQ item is the correct one
- the rate source is reasonable and supported by evidence
- the quantity values are correct
- the variation mode matches the request
- the activity selected in the schedule is the right one
- the supporting documents are relevant and readable

If something looks wrong, correct it before confirming the evaluation.

## 8. What The Result Means

The result page usually contains:

- the calculated cost impact
- the time impact or EOT indication
- the formulas used
- the evidence that supported the calculation
- any validation warnings
- a PDF download link

If the result shows warnings, treat them as review items rather than final answers.

## 9. PDF Report

The PDF report is useful when you need to share the variation proposal with others. It usually includes:

- the variation summary
- the calculation steps
- the confirmed rate source
- the time impact summary
- validation notes and assumptions

## 10. Common Problems and Simple Fixes

### The upload fails

Check that the file is not open in another app and that it is a supported format.

### The AI cannot find a good match

Try uploading a clearer supporting document or add more context in the description.

### The result looks incomplete

Make sure you confirmed the extracted data before running the evaluation.

### The PDF does not download

Refresh the page and try again, or check whether the backend service is still running.

### The page does not load

Check that the frontend and backend servers are both running and that you are using the correct local URL.

## 11. Beginner Tips

- Start with one simple variation before trying a complex case.
- Upload the best quality files you have.
- Always review the extracted candidates before confirming.
- Keep the supporting evidence with the project so the PDF report is easier to defend.

## 12. Short Example

If a client asks to change a flooring material, you would:

1. upload the BOQ item for the existing flooring
2. upload the quotation or rate breakdown for the new flooring
3. upload the schedule activity for the affected work
4. type the variation request
5. confirm the suggested matches
6. generate the result
7. download the PDF proposal

That is the basic workflow the system is designed to support.