(node) => {
  const root = node.matches('.markdown, .standard-markdown, .progressive-markdown')
    ? node
    : node.querySelector('.markdown, .standard-markdown, .progressive-markdown') || node;

  const clean = (value) => (value || '').replace(/[\u200b\ufeff]/g, '');
  const texFor = (element) => {
    const annotation = element.querySelector('annotation[encoding="application/x-tex"]');
    if (annotation?.textContent?.trim()) return annotation.textContent.trim();
    return element.getAttribute('data-tex') || element.getAttribute('alttext') || '';
  };
  const isMath = (element) => element.matches(
    '.katex, .katex-display, mjx-container, math, [data-tex], [alttext]'
  );
  const isBlockMath = (element) => element.matches(
    '.katex-display, mjx-container[display="true"], mjx-container[display="block"], math[display="block"]'
  );

  function walk(current, orderedIndex = 0) {
    if (current.nodeType === Node.TEXT_NODE) return clean(current.nodeValue);
    if (current.nodeType !== Node.ELEMENT_NODE) return '';

    const element = current;
    const tag = element.tagName.toLowerCase();
    if (['script', 'style', 'button', 'svg', 'path', 'nav'].includes(tag)) return '';

    if (isMath(element)) {
      const tex = texFor(element);
      if (tex) return isBlockMath(element) ? `\n\n$$\n${tex}\n$$\n\n` : `$${tex}$`;
    }

    const children = [...element.childNodes]
      .map((child) => walk(child, orderedIndex))
      .join('');
    const text = clean(children).trim();

    if (/^h[1-6]$/.test(tag)) return `\n\n${'#'.repeat(Number(tag[1]))} ${text}\n\n`;
    if (tag === 'p') return `\n\n${text}\n\n`;
    if (tag === 'br') return '\n';
    if (tag === 'hr') return '\n\n---\n\n';
    if (tag === 'strong' || tag === 'b') return text ? `**${text}**` : '';
    if (tag === 'em' || tag === 'i') return text ? `*${text}*` : '';
    if (tag === 'blockquote') return text.split('\n').map((line) => `> ${line}`).join('\n') + '\n\n';
    if (tag === 'code' && element.parentElement?.tagName.toLowerCase() !== 'pre') {
      return text ? `\`${text}\`` : '';
    }
    if (tag === 'pre') return `\n\n\`\`\`\n${element.innerText.trim()}\n\`\`\`\n\n`;
    if (tag === 'a') {
      const href = element.getAttribute('href');
      return href && text ? `[${text}](${href})` : text;
    }
    if (tag === 'li') return `- ${text}\n`;
    if (tag === 'ol' || tag === 'ul') return `\n${children.replace(/\n{2,}/g, '\n')}\n`;
    if (tag === 'table') return `\n\n${children}\n\n`;
    if (tag === 'thead' || tag === 'tbody') return children;
    if (tag === 'tr') {
      let isHeader = element.parentElement?.tagName?.toLowerCase() === 'thead' || 
                     [...element.children].some(c => c.tagName.toLowerCase() === 'th');
      if (!isHeader && !element.previousElementSibling) {
          const pTag = element.parentElement?.tagName?.toLowerCase();
          if (pTag === 'table' || (pTag === 'tbody' && !element.parentElement.previousElementSibling)) isHeader = true;
      }
      let row = `|${children}\n`;
      if (isHeader) row += `|${[...element.children].map(() => ' --- |').join('')}\n`;
      return row;
    }
    if (tag === 'th' || tag === 'td') return ` ${children.replace(/\n+/g, ' ').trim()} |`;
    return children;
  }

  const markdown = walk(root)
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();

  // When an app has already rendered elementary equations as ordinary text,
  // recover inline LaTex for the common voltage/current/resistance forms.
  return markdown.replace(
    /(?<![A-Za-z$])([VIR](?:[ \t]*=[ \t]*(?:[VIR]|[0-9]+(?:\.[0-9]+)?|[ΩAV]|×|\/|\+|-|[ \t])+)+)(?![A-Za-z])/g,
    (_, equation) => {
      const tex = equation.replace(/[ \t=]+$/, '')
        .replace(/Ω/g, '\\Omega')
        .replace(/×/g, '\\times')
        .replace(/([VIR0-9.]+)[ \t]*\/[ \t]*([VIR0-9.]+)/g, '\\frac{$1}{$2}');
      return `$${tex.trim()}$`;
    },
  );
}
