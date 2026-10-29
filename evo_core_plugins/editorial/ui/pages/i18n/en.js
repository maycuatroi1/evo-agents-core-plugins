// Editorial UI strings.
evo.messages("en", {
  "posts": {
    "title": "Posts",
    "sub": "Review the waiting posts or follow the writer’s progress.",
    "emptyTitle": "No post yet",
    "emptyText": "A post appears once an agent or a member sets its stage.",
    "waits": "Waits at {stage}",
    "rounds": "{count, plural, =0 {No review round} one {# review round} other {# review rounds}}",
    "preview": "Preview",
    "published": "Published",
    "back": "Posts",
    "stageIs": "Stage: {stage}",
    "gates": "Gates",
    "answered": "Answered through {via} by {by}",
    "roundsTitle": "Review rounds",
    "round": "Round {number} at {stage}",
    "history": "Stages entered",
    "feedback": "Feedback entries",
    "pullComments": "Read the comments",
    "run": {
      "title": "Writer agent",
      "at": "Run #{run} from stage {stage}",
      "error": "The writer stopped",
      "again": "Hand the next task",
      "states": {
        "running": "Running",
        "done": "Done",
        "failed": "Failed",
        "refused": "Refused"
      }
    },
    "answer": {
      "wait": "The writer agent is working on this post; answer once it stops here.",
      "pick": "Pick: {option}",
      "topic": "Or write another topic",
      "useTopic": "Use this topic",
      "needTopic": "Write the topic first.",
      "approveBrief": "Send the answers and approve the brief",
      "commentsDone": "My comments are in",
      "approveDraft": "Approve the draft",
      "url": "The published post's link",
      "published": "The post is out"
    },
    "judge": {
      "title": "Judge",
      "states": {
        "pending": "Asked",
        "passed": "Passed",
        "below": "Below 4",
        "failed": "No answer",
        "refused": "Not asked"
      },
      "axes": {
        "slop": "slop",
        "giong": "voice",
        "nguon": "sources",
        "hinh": "images"
      }
    },
    "states": {
      "waiting": "Waiting",
      "answered": "Answered",
      "skipped": "Skipped"
    },
    "kinds": {
      "choose": "choose",
      "interview": "interview",
      "comments": "comments",
      "publish": "publish"
    }
  },
  "notebook": {
    "title": "Feedback notebook",
    "sub": "Review the rules learned from feedback, with the original words and checks.",
    "emptyTitle": "No entry matches",
    "entries": "Entries",
    "seen": "{count, plural, one {Seen once} other {Seen # times}}",
    "agentWrote": "Agent wrote",
    "personFixed": "Changed to",
    "rule": "Rule",
    "check": "Check",
    "filters": {
      "notebook": "Notebook",
      "stage": "Read before stage",
      "post": "Post",
      "seen": "Seen at least"
    }
  },
  "common": {
    "retry": "Try again"
  },
  "workspace": {
    "navigation": "Editorial navigation",
    "loading": "Loading editorial workspace…",
    "refresh": "Refresh",
    "allStages": "All stages",
    "allNotebooks": "All notebooks",
    "allPosts": "All posts",
    "clear": "Clear filters",
    "search": "Search",
    "apply": "Apply filters",
    "previous": "Previous",
    "next": "Next",
    "page": "Page {page} of {pages}",
    "results": "{count, plural, =0 {No results} one {# result} other {# results}}",
    "unavailable": "Stage and notebook labels could not be loaded. You can still browse the content."
  },
  "board": {
    "search": "Search posts",
    "placeholder": "Title or slug",
    "status": "Show posts",
    "all": "All posts",
    "waiting": "Needs your review",
    "running": "Writer running",
    "published": "Published",
    "failed": "Needs attention",
    "stage": "Stage",
    "noMatch": "No posts match these filters",
    "noMatchText": "Try another title or clear the filters.",
    "open": "Open post",
    "results": "{count, plural, one {# post} other {# posts}}",
    "attention": "Review the waiting posts or follow the writer’s progress."
  },
  "feedbackUi": {
    "search": "Search feedback",
    "placeholder": "Words in the feedback or rule",
    "allSeen": "Any recurrence",
    "twice": "Seen at least twice",
    "three": "Seen at least 3 times",
    "five": "Seen at least 5 times",
    "evidence": "Original feedback",
    "details": "Read feedback and checks",
    "emptyText": "Try fewer filters or different search words.",
    "count": "{count, plural, one {# entry} other {# entries}}",
    "rule": "Writing rule",
    "check": "How to check",
    "collapse": "Collapse entries",
    "expand": "Expand entries",
    "sort": "Sort by",
    "id": "Entry order",
    "recent": "Newest first",
    "repeated": "Most repeated",
    "postPlaceholder": "Post slug",
    "note": "Agent note",
    "fixedNote": "Correction note"
  },
  "detailUi": {
    "next": "Waiting for your review",
    "pastGates": "Previous decisions",
    "currentStage": "Current stage",
    "overview": "Post overview",
    "activity": "Writing activity",
    "feedbackLink": "Open feedback for this post",
    "comments": "{count, plural, =0 {No comments} one {# comment} other {# comments}}",
    "readOnly": "You have read access. A writer or admin can answer this review.",
    "runLink": "Open run #{run}",
    "branch": "Branch"
  }
});
