export default function IslandAtlas({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      fill="none"
      preserveAspectRatio="xMidYMid slice"
      viewBox="0 0 760 760"
    >
      <g className="atlas-contours" stroke="currentColor" strokeWidth="1">
        <path d="M88 438C92 334 164 246 262 214C362 182 470 214 548 286C616 350 646 444 614 522C580 606 500 660 404 674C304 688 210 640 148 574C106 530 86 486 88 438Z" opacity="0.48" />
        <path d="M150 442C158 358 218 292 300 268C386 244 474 274 530 332C580 384 596 456 566 518C536 582 466 620 386 628C304 636 232 598 188 544C158 508 148 476 150 442Z" opacity="0.62" />
        <path d="M214 446C222 382 270 330 336 312C404 294 470 320 510 366C544 406 552 460 528 506C502 556 450 586 386 590C322 594 266 566 234 524C216 498 212 470 214 446Z" opacity="0.8" />
        <path d="M276 450C284 402 320 366 368 354C418 342 464 362 490 396C512 426 514 464 496 494C476 528 440 548 394 548C348 548 310 528 290 498C278 480 274 464 276 450Z" opacity="1" />
        <path d="M330 456C336 426 358 404 390 398C422 392 450 406 464 428C476 448 474 474 460 492C444 512 420 522 390 520C360 518 340 502 332 484C328 474 328 464 330 456Z" opacity="0.72" />
        <path d="M590 540C600 526 620 522 630 532C640 542 636 556 622 560C608 564 594 554 590 540Z" opacity="0.55" />
      </g>
      <g className="atlas-route" stroke="currentColor" strokeWidth="1" strokeDasharray="8 14" opacity="0.5">
        <path d="M206 500C300 470 380 452 448 430C520 406 570 380 612 340" />
      </g>
      <g className="atlas-nodes" fill="currentColor">
        <circle cx="206" cy="500" r="3.5" opacity="0.9" />
        <circle cx="448" cy="430" r="2.5" opacity="0.72" />
        <circle cx="612" cy="340" r="3.5" opacity="0.9" />
      </g>
      <g className="atlas-moon" stroke="currentColor">
        <circle cx="598" cy="170" r="58" opacity="0.45" strokeWidth="1" />
        <circle cx="598" cy="170" r="44" opacity="0.24" strokeWidth="0.8" />
      </g>
      <g className="atlas-ticks" stroke="currentColor" strokeWidth="0.7" opacity="0.3">
        <path d="M42 300v18M42 300h12M718 470v18M706 470h12M414 725v-15M414 725h12" />
      </g>
    </svg>
  );
}
