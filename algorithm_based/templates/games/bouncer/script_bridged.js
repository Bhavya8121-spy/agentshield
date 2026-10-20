// script_bridged.js for the "bouncer" arcade template.
// Implements the arcade bridge contract used by _arcade_scaffold.html:
//   window.setupScene(config)
//   window.generateCustomer(difficultyState) -> customer object
//   window.renderCustomer(customer)
//   window.resolveRound(customer, result)
//   window.clearScene()
//
// The customer generator is intentionally client-side and authoritative --
// there's nothing to hide from the player (they see the whole ID), so this
// mirrors how tetris's board state already works: client owns the state,
// server (/api/evaluate/<algo_key> -> evaluate_bouncer_id_check) grades it
// fresh every round.

(function () {
    const FIRST_NAMES = ["Jordan", "Sam", "Riley", "Casey", "Morgan", "Taylor", "Avery", "Quinn", "Rowan", "Skyler"];
    const LAST_NAMES = ["Lee", "Ortiz", "Chen", "Patel", "Nguyen", "Kim", "Brooks", "Ellis", "Farrow", "Vance"];

    let ctx = null;
    let legalAge = 21;

    function randomName(usedNames) {
        for (let i = 0; i < 20; i++) {
            const name = `${FIRST_NAMES[Math.floor(Math.random() * FIRST_NAMES.length)]} ${LAST_NAMES[Math.floor(Math.random() * LAST_NAMES.length)]}`;
            if (!usedNames.has(name)) return name;
        }
        return `${FIRST_NAMES[0]} ${LAST_NAMES[0]}`;
    }

    // Rolling memory of who's already been let in tonight, so the
    // "duplicate" rule has something real to check against.
    let admittedNames = new Set();

    window.setupScene = function (config) {
        legalAge = (config && config.legal_age) || 21;
        admittedNames = new Set();
        const canvas = document.getElementById('scene-canvas');
        ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
    };

    window.clearScene = function () {
        if (!ctx) return;
        ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
    };

    window.generateCustomer = function (difficultyState) {
        const streak = (difficultyState && difficultyState.streak) || 0;
        // Difficulty scales with streak, not a fixed level: as the streak
        // climbs, ages cluster closer to the legal threshold and stacked
        // violations (expired AND underage) become possible, instead of
        // one obviously-wrong attribute at a time.
        const closeCallChance = Math.min(0.15 + streak * 0.08, 0.75);
        const stackedViolationChance = Math.min(streak * 0.05, 0.3);
        const violationChance = 0.4;

        let age;
        if (Math.random() < closeCallChance) {
            // Within 2 years of the threshold on either side -- the hard case.
            age = legalAge + Math.floor(Math.random() * 5) - 2;
        } else {
            age = legalAge - 8 + Math.floor(Math.random() * 24);
        }
        age = Math.max(16, age);

        const isViolation = Math.random() < violationChance || age < legalAge;
        let idExpired = false;
        let alreadyAdmitted = false;

        if (isViolation) {
            const roll = Math.random();
            if (age < legalAge) {
                idExpired = roll < stackedViolationChance; // stacked: underage AND expired
            } else if (admittedNames.size > 0 && roll < 0.4) {
                alreadyAdmitted = true;
            } else {
                idExpired = true;
            }
        }

        const name = alreadyAdmitted
            ? Array.from(admittedNames)[Math.floor(Math.random() * admittedNames.size)]
            : randomName(admittedNames);

        const expiryYear = idExpired
            ? new Date().getFullYear() - (1 + Math.floor(Math.random() * 3))
            : new Date().getFullYear() + (1 + Math.floor(Math.random() * 3));

        return {
            name,
            age,
            legal_age: legalAge,
            id_expired: idExpired,
            already_admitted: alreadyAdmitted,
            expiry: `01/${expiryYear}`,
        };
    };

    window.renderCustomer = function (customer) {
        if (!ctx) return;
        const w = ctx.canvas.width, h = ctx.canvas.height;
        ctx.clearRect(0, 0, w, h);

        // Door frame
        ctx.strokeStyle = '#4a4a5a';
        ctx.lineWidth = 4;
        ctx.strokeRect(20, 20, w - 40, h - 40);

        // ID card
        const cardX = w / 2 - 160, cardY = h / 2 - 90, cardW = 320, cardH = 180;
        ctx.fillStyle = '#111820';
        ctx.fillRect(cardX, cardY, cardW, cardH);
        ctx.strokeStyle = '#00f3ff';
        ctx.lineWidth = 2;
        ctx.strokeRect(cardX, cardY, cardW, cardH);

        ctx.fillStyle = '#e0e0e0';
        ctx.font = '20px monospace';
        ctx.textAlign = 'left';
        ctx.fillText(customer.name, cardX + 20, cardY + 40);

        ctx.font = '16px monospace';
        ctx.fillStyle = '#94a3b8';
        ctx.fillText(`AGE: ${customer.age}`, cardX + 20, cardY + 75);
        ctx.fillText(`EXPIRES: ${customer.expiry}`, cardX + 20, cardY + 100);

        if (customer.already_admitted) {
            ctx.fillStyle = '#ff003c';
            ctx.font = '14px monospace';
            ctx.fillText('(you swear you\'ve seen this face already)', cardX + 20, cardY + 130);
        }
    };

    window.resolveRound = function (customer, result) {
        if (!ctx) return;
        // Door swings: green tint sweep for accept, red bar-drop for reject.
        // The overlay flash is handled by the driver -- this just updates
        // internal state for the duplicate-ID rule.
        if (result.correct !== false && result.best_action === 'accept') {
            admittedNames.add(customer.name);
        }
    };
})();
