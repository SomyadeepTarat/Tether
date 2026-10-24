import type {ButtonHTMLAttributes} from 'react';
import {clsx} from 'clsx';
import {twMerge} from 'tailwind-merge';
export function Button({className,variant='default',...props}:ButtonHTMLAttributes<HTMLButtonElement>&{variant?:'default'|'outline'|'danger'}) {
 return <button className={twMerge(clsx('button',variant!=='default'&&variant,className))} {...props}/>;
}
