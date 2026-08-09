package example.entity;

import java.math.BigDecimal;
import org.seasar.doma.Column;
import org.seasar.doma.Entity;
import org.seasar.doma.Id;
import org.seasar.doma.Table;

/** Invoices */
@Entity
@Table(catalog = "fixture_catalog", name = "invoice")
public class Invoice {

    /** Invoice ID */
    @Id
    @Column(name = "invoice_id")
    Long invoiceId;

    /** Total amount */
    @Column(name = "amount")
    BigDecimal amount;

    /** Returns the invoiceId. */
    public Long getInvoiceId() {
        return invoiceId;
    }

    /** Sets the invoiceId. */
    public void setInvoiceId(Long invoiceId) {
        this.invoiceId = invoiceId;
    }

    /** Returns the amount. */
    public BigDecimal getAmount() {
        return amount;
    }

    /** Sets the amount. */
    public void setAmount(BigDecimal amount) {
        this.amount = amount;
    }
}
