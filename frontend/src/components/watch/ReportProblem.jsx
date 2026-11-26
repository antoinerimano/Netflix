// "Playback problem?" (ROADMAP 9.8): what's wrong with the source on this title / episode, saved
// for the admin dashboard and re-checked first by the provider scout that night. A design system
// Modal: the remote stays inside, Back / Escape close it and the focus goes back to the button.
// After sending: try the next source (a "doesn't play" / wrong film report also counts as a
// failed play there), or the status page ("is it down for me or everyone?").
import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Modal } from "../../design";
import { PROBLEMS, reportProblem } from "../../api/problemsApi";
import "./report-problem.css";

export default function ReportProblem({ open, onClose, source, titleId, season, episode, next, onTryNext }) {
  const { t } = useTranslation("watch");
  const [state, setState] = useState("choose"); // choose | sending | sent | error
  const [problem, setProblem] = useState("");
  const bodyRef = useRef(null);

  useEffect(() => {
    if (open) {
      setState("choose");
      setProblem("");
    }
  }, [open]);

  // the answer replaces the list: the remote goes to its first button, never to nothing
  useLayoutEffect(() => {
    if (state === "sent" || state === "error") {
      bodyRef.current?.querySelector("button")?.focus({ preventScroll: true });
    }
  }, [state]);

  const send = async (p) => {
    setProblem(p);
    setState("sending");
    try {
      await reportProblem({
        profileId: localStorage.getItem("activeProfileId"),
        titleId,
        provider: source.key,
        problem: p,
        season,
        episode,
      });
      setState("sent");
    } catch {
      setState("error");
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t("problem.title")}
      size="sm"
      scrollable={false}
      initialFocus=".report-problem__option"
      className="report-problem"
      footer={
        <Button variant="ghost" onClick={onClose}>
          {t("common:actions.close")}
        </Button>
      }
    >
      <div ref={bodyRef} aria-live="polite">
        {state === "choose" || state === "sending" ? (
          <>
            <p className="report-problem__question">{t("problem.question", { source: source?.label })}</p>
            <div className="report-problem__options" role="group" aria-label={t("problem.title")}>
              {PROBLEMS.map((p) => (
                <Button
                  key={p}
                  variant="secondary"
                  className="report-problem__option"
                  onClick={() => state !== "sending" && send(p)} // not disabled: the focus would drop to nothing
                  aria-busy={state === "sending" && problem === p ? "true" : undefined}
                >
                  {t(`problem.kinds.${p}`)}
                </Button>
              ))}
            </div>
            <p className="report-problem__note">{t("problem.note")}</p>
          </>
        ) : null}

        {state === "sent" ? (
          <>
            <p className="report-problem__thanks">{t("problem.thanks", { source: source?.label })}</p>
            <div className="report-problem__actions">
              {next ? (
                <Button variant="primary" onClick={() => onTryNext(next.key)}>
                  {t("sources.try", { source: next.label })}
                </Button>
              ) : null}
              <Button variant="secondary" to="/status">
                {t("problem.status")}
              </Button>
            </div>
          </>
        ) : null}

        {state === "error" ? (
          <>
            <p className="report-problem__thanks">{t("problem.failed")}</p>
            <div className="report-problem__actions">
              <Button variant="primary" onClick={() => send(problem)}>
                {t("sources.tryAgain")}
              </Button>
            </div>
          </>
        ) : null}
      </div>
    </Modal>
  );
}
