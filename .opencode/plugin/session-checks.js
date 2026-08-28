// Analog of the Claude Code `PostToolUse` hook in .claude/settings.json: it
// fires after every Write/Edit of a non-test .py file and injects a reminder
// to check CLAUDE.md's doc-update trigger table before calling the task done.
// That hook only ever adds context — it has no `{"decision":"block"}` — so
// this plugin loses nothing by being equally advisory. Under opencode there
// is no enforcement layer either harness can lean on here; both just nag.
//
// tool.execute.after is the direct analog of PostToolUse: it fires once per
// tool call, after the call, and can append to what the model sees in the
// tool's own result (`output.output`), same delivery mechanism Claude Code
// uses for `additionalContext`.
//
// Stay silent unless a file that should carry the reminder was actually
// touched — a checker that talks on every turn gets ignored.

const REMINDER =
  "[CLAUDE.md doc-update] Modified {path} — check the trigger table in " +
  "CLAUDE.md (`## Documentation files`) and update README.md / " +
  "ARCHITECTURE.md / STATUS.md / SETUP.md before completing this task."

function isReminderWorthy(filePath) {
  if (!filePath || !filePath.endsWith(".py")) return false
  const base = filePath.split("/").pop()
  return !filePath.includes("/tests/") && !base.startsWith("test_")
}

export const IbkrSessionChecks = async () => {
  return {
    "tool.execute.after": async (input, output) => {
      if (input.tool !== "edit" && input.tool !== "write") return
      const args = input.args || {}
      const filePath = args.filePath || args.file_path || args.path
      if (!isReminderWorthy(filePath)) return
      output.output += `\n\n${REMINDER.replace("{path}", filePath)}`
    },
  }
}
