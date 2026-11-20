import { Link as RouterLink, type LinkProps } from "react-router-dom";

/** Existing view markup uses href; navigation is owned by React Router. */
export default function Link({
  href,
  ...props
}: Omit<LinkProps, "to"> & { href: string }) {
  return <RouterLink to={href} {...props} />;
}
