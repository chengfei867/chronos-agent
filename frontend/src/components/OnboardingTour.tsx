// First-visit guided tour. Persists dismissal in localStorage.
import { useEffect, useState } from "react";
import { Tour } from "antd";
import type { TourProps } from "antd";
import { useTranslation } from "react-i18next";

const TOUR_KEY = "chronos.tour.seen.v1";

export default function OnboardingTour({
  onHelpClick,
}: {
  onHelpClick: () => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    // Delay so target elements are in the DOM.
    const seen = localStorage.getItem(TOUR_KEY);
    if (!seen) {
      const timer = setTimeout(() => setOpen(true), 600);
      return () => clearTimeout(timer);
    }
    return undefined;
  }, []);

  const dismiss = () => {
    localStorage.setItem(TOUR_KEY, "1");
    setOpen(false);
  };

  const steps: TourProps["steps"] = [
    {
      title: t("tour.steps.welcome.title"),
      description: t("tour.steps.welcome.description"),
      target: null,
    },
    {
      title: t("tour.steps.runList.title"),
      description: t("tour.steps.runList.description"),
      target: () => document.querySelector("#tour-anchor-runs") as HTMLElement,
    },
    {
      title: t("tour.steps.help.title"),
      description: t("tour.steps.help.description"),
      target: () => document.querySelector("#tour-anchor-help") as HTMLElement,
      nextButtonProps: {
        children: t("tour.next"),
        onClick: () => onHelpClick(),
      },
    },
    {
      title: t("tour.steps.lang.title"),
      description: t("tour.steps.lang.description"),
      target: () => document.querySelector("#tour-anchor-lang") as HTMLElement,
    },
  ];

  return (
    <Tour
      open={open}
      onClose={dismiss}
      onFinish={dismiss}
      steps={steps}
      indicatorsRender={(current, total) => (
        <span style={{ color: "#8b949e" }}>{current + 1} / {total}</span>
      )}
    />
  );
}
