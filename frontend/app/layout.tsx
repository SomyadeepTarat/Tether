import type {Metadata} from 'next';
import './globals.css';
export const metadata:Metadata={title:'Tether — Keep the goal in sight',description:'Persistent goal alignment for local AI workflows'};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="en"><body>{children}</body></html>;}
